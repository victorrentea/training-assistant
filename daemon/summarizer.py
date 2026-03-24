"""
Summarizer — generates key discussion points from live transcript.

Called on-demand by the daemon. Reads the full transcript and session notes,
returns {"points": [...]} with a fresh complete list of all key points.
"""

import json
import sys
from typing import Optional

import anthropic
from daemon.llm_adapter import create_message
from daemon.project_files import get_project_tools, handle_project_tool_call, PROJECT_TOOL_NAMES

from quiz_core import (
    Config,
    load_transcription_files,
    extract_all_text,
    read_session_notes,
)

SUMMARY_INTERVAL_SECONDS = 5 * 60  # 5 minutes

_SUMMARY_SYSTEM_PROMPT = """\
You are a technical workshop summarizer. You extract high-density takeaways from a live session.

Input: full session transcript and/or trainer's session notes.

Output rules:
- Each bullet: ONE actionable or factual technical statement (max 15 words).
- Write like a cheat-sheet: name patterns, tools, trade-offs, rules-of-thumb, commands, gotchas.
- GOOD: "Extract Method refactoring reduces cyclomatic complexity per function"
- GOOD: "@Transactional on private methods is silently ignored by Spring AOP"
- BAD: "Participants shared experiences about refactoring" (vague, no knowledge)
- BAD: "Session ended with informal discussion" (filler, no takeaway)
- BAD: "The trainer demonstrated an interesting approach" (meta-commentary)
- Never describe what happened socially — only capture WHAT was taught or concluded.
- Capture every important detail — aim for high density, don't leave out valuable ideas.
- Ignore transcription noise, filler, off-topic chatter, and garbled dictation.
- For each bullet, indicate source:
  - "notes" if it comes primarily from SESSION NOTES (trainer's agenda/material)
  - "discussion" if it comes primarily from TRANSCRIPT (what was actually said)
- For each bullet, include "time": the approximate timestamp (HH:MM format, 24h) when the topic was discussed. Omit "time" for bullets derived solely from session notes with no transcript match.

Response format — return ONLY a JSON object:
{"points": [{"text": "...", "source": "discussion"|"notes", "time": "HH:MM"}, ...]}

Omit "time" for notes-only bullets.

## Project Source Code
If `list_project_tree` and `read_project_file` tools are available, use them to find relevant source files when the transcript mentions specific classes, patterns, or configurations. Include specific class/method references in your key points.
"""


def generate_summary(
    config: Config,
) -> Optional[dict]:
    """Generate a fresh complete list of key points from the full transcript and session notes.
    Returns {"points": [...]} or None on failure.
    """
    # Load full transcript
    try:
        entries = load_transcription_files(config.folder)
    except SystemExit:
        print("[summarizer] No transcription files found — skipping", file=sys.stderr)
        return None

    text = None
    if entries:
        text = extract_all_text(entries)

    # Include session notes if available
    notes = read_session_notes(config)

    if not text and not notes:
        print("[summarizer] No transcript or notes available — skipping", file=sys.stderr)
        return None

    # Build user message
    parts = []
    if notes:
        parts.append(f"SESSION NOTES (trainer's agenda/material):\n{notes}\n")
    if text:
        parts.append(f"FULL SESSION TRANSCRIPT:\n{text}")

    user_message = "\n---\n".join(parts)

    try:
        # Build tools list (project file tools if configured)
        tools = get_project_tools(config.project_folder)

        messages = [{"role": "user", "content": user_message}]

        # max_tokens bumped from 1024 to 2048 to accommodate tool-use round-trips
        create_kwargs = dict(
            api_key=config.api_key,
            model=config.model,
            max_tokens=2048,
            system=_SUMMARY_SYSTEM_PROMPT,
            messages=messages,
        )
        if tools:
            create_kwargs["tools"] = tools

        print(f"🟢🟢🟢 Sending to Claude ({len(user_message)} chars)…")
        while True:
            response = create_message(**create_kwargs)
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                tool_use_blocks = [c for c in response.content if c.type == "tool_use"]
                tool_results = []
                for tool_call in tool_use_blocks:
                    if tool_call.name in PROJECT_TOOL_NAMES:
                        result = handle_project_tool_call(
                            tool_call.name, tool_call.input, config.project_folder
                        )
                    else:
                        result = f"Error: unknown tool '{tool_call.name}'"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call.id,
                        "content": result,
                    })
                messages.append({"role": "user", "content": tool_results})
                continue
            else:
                break

        print(f"⭐⭐⭐ Response received from Claude")
        if not response.content:
            print(f"[summarizer] Empty response from Claude (stop_reason={response.stop_reason})", file=sys.stderr)
            return None

        block = response.content[0]
        if block.type != "text":
            print(f"[summarizer] Unexpected content block type: {block.type}", file=sys.stderr)
            return None

        response_text = block.text.strip()
        if not response_text:
            print(f"[summarizer] Claude returned empty text (stop_reason={response.stop_reason})", file=sys.stderr)
            return None

        # Strip markdown code fences if Claude wraps JSON in them
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            response_text = "\n".join(lines).strip()

        # Parse JSON from response
        parsed = json.loads(response_text)

        # Accept both {"points": [...]} and flat array formats
        raw_list = None
        if isinstance(parsed, list):
            raw_list = parsed
        elif isinstance(parsed, dict) and "points" in parsed:
            raw_list = parsed["points"]
        else:
            print(f"[summarizer] Unexpected response format: {response_text[:200]}", file=sys.stderr)
            return None

        points = []
        for item in raw_list:
            if isinstance(item, dict) and "text" in item:
                source = item.get("source", "discussion")
                if source not in ("notes", "discussion"):
                    source = "discussion"
                point = {"text": item["text"], "source": source}
                if item.get("time"):
                    point["time"] = item["time"]
                points.append(point)
            elif isinstance(item, str):
                points.append({"text": item, "source": "discussion"})

        result = {"points": points}
        print(f"[summarizer] Generated {len(points)} key points")
        return result

    except json.JSONDecodeError as e:
        print(f"[summarizer] Failed to parse Claude response as JSON: {e}", file=sys.stderr)
        print(f"[summarizer] Raw response: {response_text[:500]}", file=sys.stderr)
        return None
    except anthropic.APIError as e:
        print(f"[summarizer] Claude API error: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[summarizer] Unexpected error: {e}", file=sys.stderr)
        return None
