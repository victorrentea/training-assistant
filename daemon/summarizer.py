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
    load_transcription_files,
    extract_last_n_minutes,
    read_session_notes,
)

SUMMARY_INTERVAL_SECONDS = 5 * 60  # 5 minutes
SUMMARY_TRANSCRIPT_MINUTES = 30

_SUMMARY_SYSTEM_PROMPT = """\
You are a workshop summarizer. You receive the transcript of the last portion of a live technical workshop, \
optionally session notes (trainer's written agenda), and optionally a list of key points previously identified.

Your job is to produce an updated list of key discussion points — concise bullets that capture \
what was discussed, decided, or demonstrated.

Rules:
- Each bullet should be ONE concise sentence (max 15 words).
- Keep bullets in chronological order of when the topic was discussed.
- If existing bullets are provided, preserve ones that are still relevant, update ones that evolved, \
and add new ones for newly discussed topics.
- Remove bullets that are no longer relevant (e.g., a topic that was briefly mentioned but moved on from).
- Aim for 5-15 bullets total. Fewer is better if the session is short.
- Ignore transcription noise, filler words, and off-topic chatter.
- Focus on technical content, decisions, and key takeaways.
- For each bullet, indicate the source:
  - "notes" if the point comes primarily from the SESSION NOTES (trainer's agenda/material)
  - "discussion" if the point comes primarily from the TRANSCRIPT (what was actually said)

Return ONLY a JSON array of objects. No markdown, no explanation.
Example: [{"text": "Introduced TDD red-green-refactor cycle", "source": "discussion"}, \
{"text": "Planned exercise on mocking patterns", "source": "notes"}]
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

    text = extract_last_n_minutes(entries, SUMMARY_TRANSCRIPT_MINUTES)
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
    parts.append(f"TRANSCRIPT (last {SUMMARY_TRANSCRIPT_MINUTES} minutes):\n{text}")

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
