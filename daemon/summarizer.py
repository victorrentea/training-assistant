"""
Summarizer — generates key discussion points from live transcript.

Called periodically by the daemon. Reads last 30 min of transcript +
existing bullet list, calls Claude to synthesize updated key points.
"""

import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import anthropic

from quiz_core import (
    Config,
    DEFAULT_TRANSCRIPT_MINUTES,
    load_transcription_files,
    extract_last_n_minutes,
    read_session_notes,
)

SUMMARY_INTERVAL_SECONDS = 5 * 60  # 5 minutes

_SUMMARY_SYSTEM_PROMPT = """\
You are a technical workshop summarizer. You extract high-density takeaways from a live session.

Input: transcript excerpt, optionally trainer's session notes, optionally previous key points.

Output rules:
- Each bullet: ONE actionable or factual technical statement (max 15 words).
- Write like a cheat-sheet: name patterns, tools, trade-offs, rules-of-thumb, commands, gotchas.
- GOOD: "Extract Method refactoring reduces cyclomatic complexity per function"
- GOOD: "@Transactional on private methods is silently ignored by Spring AOP"
- BAD: "Participants shared experiences about refactoring" (vague, no knowledge)
- BAD: "Session ended with informal discussion" (filler, no takeaway)
- BAD: "The trainer demonstrated an interesting approach" (meta-commentary)
- Never describe what happened socially — only capture WHAT was taught or concluded.
- Chronological order. 5-15 bullets. Fewer is better if session is short.
- Preserve still-relevant existing bullets, update evolved ones, drop stale ones.
- Ignore transcription noise, filler, off-topic chatter.
- For each bullet, indicate source:
  - "notes" if it comes primarily from SESSION NOTES (trainer's agenda/material)
  - "discussion" if it comes primarily from TRANSCRIPT (what was actually said)

Return ONLY a JSON array of objects. No markdown, no explanation.
Example: [{"text": "Outbox pattern decouples DB writes from message publishing", "source": "discussion"}, \
{"text": "Hands-on: implement Circuit Breaker with Resilience4j", "source": "notes"}]
"""


def generate_summary(
    config: Config,
    existing_points: list[dict],
) -> Optional[list[dict]]:
    """Generate updated summary points from transcript + existing bullets.

    Returns updated list of bullet strings, or None on failure.
    """
    try:
        entries = load_transcription_files(config.folder)
    except SystemExit:
        print("[summarizer] No transcription files found — skipping", file=sys.stderr)
        return None

    if not entries:
        return None

    text = extract_last_n_minutes(entries, DEFAULT_TRANSCRIPT_MINUTES)
    if not text:
        return None

    # Include session notes if available
    notes = read_session_notes(config)

    # Build user message
    parts = []
    if notes:
        parts.append(f"SESSION NOTES (trainer's agenda):\n{notes}\n")
    if existing_points:
        parts.append(f"EXISTING KEY POINTS:\n{json.dumps(existing_points, indent=2)}\n")
    parts.append(f"TRANSCRIPT (last {DEFAULT_TRANSCRIPT_MINUTES} minutes):\n{text}")

    user_message = "\n---\n".join(parts)

    try:
        client = anthropic.Anthropic(api_key=config.api_key)
        response = client.messages.create(
            model=config.model,
            max_tokens=1024,
            system=_SUMMARY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

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

        # Parse JSON array from response
        parsed = json.loads(response_text)
        if not isinstance(parsed, list):
            print(f"[summarizer] Unexpected response format: {response_text[:200]}", file=sys.stderr)
            return None

        # Normalize: accept both object format and legacy plain strings
        points = []
        for item in parsed:
            if isinstance(item, dict) and "text" in item:
                source = item.get("source", "discussion")
                if source not in ("notes", "discussion"):
                    source = "discussion"
                points.append({"text": item["text"], "source": source})
            elif isinstance(item, str):
                points.append({"text": item, "source": "discussion"})
            else:
                print(f"[summarizer] Skipping invalid item: {item}", file=sys.stderr)

        # Prepend today's date as the first bullet
        date_text = f"Session date: {date.today().isoformat()}"
        points = [p for p in points if not p["text"].startswith("Session date:")]
        points.insert(0, {"text": date_text, "source": "notes"})

        print(f"[summarizer] Generated {len(points)} key points")
        return points

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
