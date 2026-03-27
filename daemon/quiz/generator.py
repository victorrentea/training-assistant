"""
Quiz generation and refinement via Claude API.
"""

import json
import re

import anthropic

from daemon import log
from daemon.config import Config
from daemon.llm.adapter import create_message

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a quiz generator for technical training sessions.
You receive EITHER a transcript excerpt from a live workshop OR a specific topic/concept.
Your goal is to produce exactly ONE poll question designed to spark discussion among participants.
The question may have one OR multiple expected answers — choose whichever fits best.

Important transcript-quality warning:
- Live transcription may contain gibberish, repeated words, filler noise, speaker confusion, or nonsense fragments.
- Treat low-signal fragments as noise and prioritize coherent, repeated concepts that clearly appear in the transcript.
- Do not build the question around obvious transcription artifacts.

You have access to a tool `search_materials` that searches through technical materials.
Each result includes a `source_type` field: "slides" (workshop slides) or "book" (books/articles).
If you receive a topic or if the transcript mentions a complex pattern (like Outbox, Circuit Breaker, Resilience),
USE THE TOOL to find more details, nuances, and real-world examples to craft a better question.

When transcript text is provided, workflow priority is:
1) First identify the main topics from the transcript itself.
2) Build the question around those transcript topics.
3) Only then use reference materials (slides first, books second) to add depth, nuance, or examples.
4) Do not let reference materials override the main transcript focus.

IMPORTANT — source priority:
- PREFER slides over books: slides reflect exactly what the audience has seen and discussed.
  Use book content to add depth or nuance only when slides don't cover the concept.
- In the "source" field of your JSON response, mention the source type explicitly,
  e.g. "Circuit Breaker Slides, p. 12" or "Microservices Patterns (book), p. 85".

Also consult https://martinfowler.com/ for authoritative articles on patterns, architecture, and software design —
it is an excellent reference for grounding questions in well-known expert opinions and named concepts.

Respond with ONLY a valid JSON object in this exact schema:
{
  "question": "<the question text>",
  "options": ["<option A>", "<option B>", "<option C>", "<option D>"],
  "correct_indices": [<zero-based index>, ...],
  "source": "<Document Name, e.g. Microservices Patterns>",
  "page": "<Page number or reference, e.g. 85>"
}

Rules:
- If you used the tool, you MUST fill in the "source" and "page" fields based on the tool's output. Include source_type in the source name (e.g. "Circuit Breaker Slides, p. 12" or "Microservices Patterns (book), p. 85"). Prefer slide sources; use book sources only for depth.
- If a "QUESTIONS ALREADY ASKED THIS SESSION" section is provided, you MUST NOT generate a question that covers the same concept or tests the same knowledge — choose a clearly different topic or angle.
- The question must probe understanding of a CONCEPT, not trivial recall.
- Prefer questions where the answer is not obvious at first glance — the goal is to trigger debate.
- Draw on your broad knowledge AND the retrieved materials to craft richer, more nuanced options.
- Include at least one option that references a real-world pattern, anti-pattern, or expert opinion.
- Each option must be concise enough for a poll display (max 80 characters).
- Do not add any explanation, markdown code fences, or text outside the JSON object.

## Project Source Code
If `list_project_tree` and `read_project_file` tools are available, you have access to the training project's source code. When the transcript discusses specific classes, patterns, or configurations, use these tools to find the actual code and reference real class names, method signatures, and line numbers in your quiz questions. Start with `list_project_tree` to discover the project structure, then `read_project_file` for specific files mentioned in the transcript.
"""


_REFINE_OPTION_PROMPT = """\
The trainer wants to replace option {letter} ("{old_text}") with a different alternative.
Generate a new option that is distinct from all current options, plausible, and consistent
with the question and the training transcript.
Return the COMPLETE updated quiz JSON (same schema as before).
Return ONLY the JSON, no explanation.
"""

_REFINE_QUESTION_PROMPT = """\
The trainer wants an entirely new question with new options, based on the same transcript.
Generate a fresh question that covers a DIFFERENT concept than the current one.
Return the COMPLETE updated quiz JSON (same schema as before).
Return ONLY the JSON, no explanation.
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_raw_response(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to find JSON block
        match = re.search(r"(\{.*\})", raw, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise


def _quiz_error(msg: str, raw: str) -> None:
    log.error("quiz", f"Invalid format: {msg}")
    raise RuntimeError(f"Invalid quiz format: {msg}")


def _validate_quiz(quiz: dict, raw: str) -> None:
    if not isinstance(quiz.get("question"), str) or not quiz["question"].strip():
        _quiz_error("Missing or empty 'question'", raw)
    options = quiz.get("options")
    if not isinstance(options, list) or not (2 <= len(options) <= 8):
        _quiz_error("'options' must be a list of 2-8 strings", raw)
    if not all(isinstance(o, str) and o.strip() for o in options):
        _quiz_error("Each option must be a non-empty string", raw)
    ci = quiz.get("correct_indices")
    if not isinstance(ci, list) or len(ci) == 0 or not all(isinstance(i, int) and 0 <= i < len(options) for i in ci):
        _quiz_error(f"'correct_indices' must be a non-empty list of ints in range 0-{len(options)-1}", raw)


def _search_materials(query: str) -> list:
    """Delegate to daemon/rag.py if available; graceful fallback otherwise."""
    try:
        from daemon.rag import search_materials as _search
        return _search(query)
    except ImportError:
        return [{"content": "RAG not available (run: pip install -e daemon/).", "source": "N/A", "page": "N/A"}]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_quiz(text: str, config: Config) -> dict:
    prompt_content = text
    if config.topic:
        prompt_content = f"TOPIC: {config.topic}\n\n{text}" if text else f"TOPIC: {config.topic}"

    log.info("quiz", f"Requesting: {config.topic or f'last {config.minutes} min'}")

    tools = [
        {
            "name": "search_materials",
            "description": "Search through technical materials (slides and books) for concepts like Outbox, Circuit Breaker, Resilience, etc. Each result includes source_type ('slides' or 'book'). Prefer slides results as the audience has seen them.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query (e.g. 'Transactional Outbox pattern details')"}
                },
                "required": ["query"]
            }
        }
    ]
    from daemon.rag.project_files import get_project_tools, handle_project_tool_call, PROJECT_TOOL_NAMES
    tools.extend(get_project_tools(config.project_folder))

    messages = [{"role": "user", "content": prompt_content}]

    try:
        while True:
            response = create_message(
                api_key=config.api_key,
                model=config.model, max_tokens=1000,
                system=_SYSTEM_PROMPT,
                messages=messages,
                tools=tools
            )

            # Append assistant's response to conversation
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                tool_use_blocks = [c for c in response.content if c.type == "tool_use"]

                tool_results = []
                for tool_call in tool_use_blocks:
                    if tool_call.name == "search_materials":
                        log.info("quiz", f"Claude searching: {tool_call.input['query']}")
                        search_results = _search_materials(tool_call.input["query"])
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_call.id,
                            "content": json.dumps(search_results)
                        })
                    elif tool_call.name in PROJECT_TOOL_NAMES:
                        result = handle_project_tool_call(
                            tool_call.name, tool_call.input, config.project_folder
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_call.id,
                            "content": result
                        })
                    else:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_call.id,
                            "content": f"Error: unknown tool '{tool_call.name}'"
                        })

                # Append ALL tool results as a single user message
                messages.append({
                    "role": "user",
                    "content": tool_results
                })
                # Continue the loop
            else:
                raw = response.content[0].text
                break

    except anthropic.APIError as e:
        raise RuntimeError(f"Claude API error — {e}") from e

    try:
        quiz = _parse_raw_response(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Claude returned invalid JSON: {e}") from e
    _validate_quiz(quiz, raw)
    return quiz


def refine_quiz(quiz: dict, target: str, original_text: str, config: Config) -> dict:
    """Refine quiz using multi-turn conversation. target='question' or 'opt0'..'opt7'."""
    if target == "question":
        refine_prompt = _REFINE_QUESTION_PROMPT
    else:
        idx = int(target[3:])  # 'opt2' -> 2
        old_text = quiz["options"][idx] if idx < len(quiz["options"]) else "?"
        letter = chr(65 + idx)
        refine_prompt = _REFINE_OPTION_PROMPT.format(letter=letter, old_text=old_text)

    # Truncate transcript to save tokens — the quiz JSON already captures the key context
    REFINE_CONTEXT_CHARS = 5_000
    if len(original_text) > REFINE_CONTEXT_CHARS:
        truncated = original_text[-REFINE_CONTEXT_CHARS:]
        context_note = f"[Transcript context — last {len(truncated)} chars of {len(original_text)} total]\n{truncated}"
    else:
        context_note = original_text

    # Multi-turn: transcript -> first generation -> refine request
    messages = [
        {"role": "user", "content": context_note},
        {"role": "assistant", "content": json.dumps(quiz)},
        {"role": "user", "content": refine_prompt},
    ]
    try:
        response = create_message(
            api_key=config.api_key,
            model=config.model, max_tokens=600,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )
    except anthropic.APIError as e:
        raise RuntimeError(f"Claude API error: {e}") from e
    raw = response.content[0].text
    try:
        updated = _parse_raw_response(raw)
    except json.JSONDecodeError:
        return quiz
    _validate_quiz(updated, raw)
    return updated


def print_quiz(quiz: dict) -> None:
    correct = set(quiz.get("correct_indices", []))
    log.info("quiz", "=" * 50)
    log.info("quiz", f"Q: {quiz['question']}")
    for i, opt in enumerate(quiz["options"]):
        marker = " <--" if i in correct else ""
        log.info("quiz", f"  {chr(65 + i)}. {opt}{marker}")
    if len(correct) > 1:
        log.info("quiz", f"  (multiple: {', '.join(chr(65+i) for i in sorted(correct))})")
    if quiz.get("source"):
        log.info("quiz", f"  source={quiz['source']} page={quiz.get('page', 'N/A')}")
    log.info("quiz", "=" * 50)
