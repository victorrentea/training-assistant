"""Debate AI cleanup — called by the daemon when backend requests it."""
import json

from daemon.llm.adapter import create_message


def run_debate_ai_cleanup(request: dict, api_key: str, model: str) -> dict:
    """Call Claude to clean up debate arguments. Returns JSON result dict.

    Args:
        request: {"statement": str, "for_args": [...], "against_args": [...]}
        api_key: Anthropic API key
        model: Claude model to use

    Returns:
        {"merges": [...], "cleaned": [...], "new_arguments": [...]}
    """
    statement = request["statement"]
    for_args = request["for_args"]
    against_args = request["against_args"]

    prompt = f"""You are helping clean up debate arguments about: "{statement}"

FOR arguments:
{chr(10).join(f'- [{a["id"]}] {a["text"]}' for a in for_args)}

AGAINST arguments:
{chr(10).join(f'- [{a["id"]}] {a["text"]}' for a in against_args)}

Tasks:
1. Identify duplicates — return which argument IDs should be merged (keep the better-worded one)
2. For each surviving argument, return a cleaned version (fix typos, make concise, preserve intent)
3. Add 2-4 NEW arguments that participants missed (mark side as "for" or "against")

Return JSON (no markdown fences):
{{
  "merges": [{{"keep_id": "...", "remove_ids": ["..."]}}],
  "cleaned": [{{"id": "...", "text": "cleaned text"}}],
  "new_arguments": [{{"side": "for"|"against", "text": "..."}}]
}}"""

    response = create_message(
        api_key=api_key,
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = response.content[0].text.strip()
    # Strip markdown fences if Claude wrapped the JSON
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text[: -len("```")].rstrip()

    return json.loads(raw_text)
