"""
Summarizer — generates key discussion points from live transcript.

Called periodically by the daemon. Reads last 30 min of transcript,
receives existing points as context, returns {"updated": [...], "new": [...]}
with in-place updates and new takeaways.
"""

import json
import sys
from typing import Optional

import anthropic
from daemon.llm_adapter import create_message
from daemon.project_files import get_project_tools, handle_project_tool_call, PROJECT_TOOL_NAMES

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

Input: transcript excerpt, optionally trainer's session notes, optionally recent key points with indices that you may update.

Output rules:
- Each bullet: ONE actionable or factual technical statement (max 15 words).
- Write like a cheat-sheet: name patterns, tools, trade-offs, rules-of-thumb, commands, gotchas.
- GOOD: "Extract Method refactoring reduces cyclomatic complexity per function"
- GOOD: "@Transactional on private methods is silently ignored by Spring AOP"
- BAD: "Participants shared experiences about refactoring" (vague, no knowledge)
- BAD: "Session ended with informal discussion" (filler, no takeaway)
- BAD: "The trainer demonstrated an interesting approach" (meta-commentary)
- Never describe what happened socially — only capture WHAT was taught or concluded.
- Ignore transcription noise, filler, off-topic chatter.
- For each bullet, indicate source:
  - "notes" if it comes primarily from SESSION NOTES (trainer's agenda/material)
  - "discussion" if it comes primarily from TRANSCRIPT (what was actually said)
- For each bullet, include "time": the approximate timestamp (HH:MM format, 24h) when the topic was discussed. Omit "time" for bullets derived solely from session notes with no transcript match.

Response format — return ONLY a JSON object with two arrays:
- "updated": points that REVISE an existing key point (include "index" matching the provided index). Use when new discussion adds to, corrects, or refines an existing point.
- "new": entirely new takeaways not covered by existing points.

Example:
{"updated": [{"index": 2, "text": "Revised point with new info", "source": "discussion", "time": "14:30"}], "new": [{"text": "Brand new takeaway", "source": "discussion", "time": "15:10"}]}

If nothing to update, return {"updated": [], "new": [...]}.
If nothing new, return {"updated": [...], "new": []}.

## Project Source Code
If `list_project_tree` and `read_project_file` tools are available, use them to find relevant source files when the transcript mentions specific classes, patterns, or configurations. Include specific class/method references in your key points.
"""


def generate_summary(
    config: Config,
    existing_points: list[dict],
    delta_text: str | None = None,
) -> Optional[dict]:
    """Generate summary updates from transcript, given existing points as context. Returns {"updated": [...], "new": [...]} or None on failure.

    When delta_text is provided and non-empty, it is used instead of loading
    the full transcript — this sends only incremental content to the LLM.
    """
    if delta_text:
        text = delta_text
        transcript_label = "INCREMENTAL TRANSCRIPT (new content since last summary)"
    else:
        # Fall back to loading full transcript
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
        transcript_label = f"TRANSCRIPT (last {DEFAULT_TRANSCRIPT_MINUTES} minutes)"

    # Include session notes if available
    notes = read_session_notes(config)

    # Build user message
    parts = []
    if notes:
        parts.append(f"SESSION NOTES (trainer's agenda):\n{notes}\n")
    if existing_points:
        indexed_texts = "\n".join(f"  [{i}] {p['text']}" for i, p in enumerate(existing_points))
        parts.append(f"RECENT KEY POINTS (you may update by index, or add new):\n{indexed_texts}\n")
    parts.append(f"{transcript_label}:\n{text}")

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

        # Backward compat: if LLM returns a flat array, wrap as all-new
        if isinstance(parsed, list):
            new_points = []
            for item in parsed:
                if isinstance(item, dict) and "text" in item:
                    source = item.get("source", "discussion")
                    if source not in ("notes", "discussion"):
                        source = "discussion"
                    point = {"text": item["text"], "source": source}
                    if item.get("time"):
                        point["time"] = item["time"]
                    new_points.append(point)
                elif isinstance(item, str):
                    new_points.append({"text": item, "source": "discussion"})
            parsed = {"updated": [], "new": new_points}

        if not isinstance(parsed, dict) or "new" not in parsed:
            print(f"[summarizer] Unexpected response format: {response_text[:200]}", file=sys.stderr)
            return None

        # Normalize updated entries
        updated = []
        for item in parsed.get("updated", []):
            if isinstance(item, dict) and "text" in item and "index" in item:
                source = item.get("source", "discussion")
                if source not in ("notes", "discussion"):
                    source = "discussion"
                entry = {"index": item["index"], "text": item["text"], "source": source}
                if item.get("time"):
                    entry["time"] = item["time"]
                updated.append(entry)

        # Normalize new entries
        new_pts = []
        for item in parsed.get("new", []):
            if isinstance(item, dict) and "text" in item:
                source = item.get("source", "discussion")
                if source not in ("notes", "discussion"):
                    source = "discussion"
                point = {"text": item["text"], "source": source}
                if item.get("time"):
                    point["time"] = item["time"]
                new_pts.append(point)
            elif isinstance(item, str):
                new_pts.append({"text": item, "source": "discussion"})

        result = {"updated": updated, "new": new_pts}
        print(f"[summarizer] Generated {len(updated)} updates + {len(new_pts)} new points")
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
