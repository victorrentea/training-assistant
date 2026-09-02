"""Session notes/summary readers from active session folder on disk."""
from __future__ import annotations

import re
from pathlib import Path

from daemon.session import state as session_shared_state
from daemon.session_state import find_notes_in_folder
from daemon.summary.loop import get_ai_summary_mtime, get_ai_summary_raw

AI_SUMMARY_FILE = "ai-summary.md"


def get_active_session_folder() -> Path | None:
    root = session_shared_state.get_sessions_root()
    name = session_shared_state.get_active_session_name()
    if root is None or not name:
        return None
    folder = root / str(name)
    if not folder.exists() or not folder.is_dir():
        return None
    return folder


def read_notes_updated_at() -> str | None:
    """Return ISO timestamp of the notes file mtime, or None if no notes file exists."""
    folder = get_active_session_folder()
    if folder is None:
        return None
    notes_file = find_notes_in_folder(folder)
    if notes_file is None:
        return None
    try:
        mtime_ns = notes_file.stat().st_mtime_ns
    except OSError:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(mtime_ns / 1e9, tz=timezone.utc).isoformat()


def read_notes_content() -> str | None:
    folder = get_active_session_folder()
    if folder is None:
        return None
    notes_file = find_notes_in_folder(folder)
    if notes_file is None:
        return None
    try:
        text = notes_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return text if text.strip() else None


# Lines the macOS addon appends for an INTERCEPTED AGENT PROMPT look like
# "- 🤖 <prompt>" (SessionNotesAppender.Marker.agentPrompt); text the trainer
# sent by hand carries 📋 instead. The 🤖 stamp is therefore the only thing that
# separates "this went to a coding agent" from every other line in the notes,
# which is exactly the distinction the participants' Prompts tab is made of.
#
# A dictated prompt is a single line. A pasted multi-line one keeps its newlines
# and only its FIRST line carries the marker, so an entry runs from its marker
# line through the following non-blank lines that start neither a new bullet nor
# one of Victor's "=== section" headers. That is the conservative rule: it never
# swallows the hand-typed notes that follow a prompt.
_PROMPT_LINE_RE = re.compile(r"^-\s*\U0001F916\uFE0F?\s*(.*)$")


def parse_prompts(notes_text: str | None) -> list[str]:
    """Intercepted agent prompts found in `notes_text`, oldest first."""
    if not notes_text:
        return []
    prompts: list[str] = []
    current: list[str] | None = None

    def flush() -> None:
        nonlocal current
        if current is not None:
            entry = "\n".join(current).strip()
            if entry:
                prompts.append(entry)
            current = None

    for line in notes_text.splitlines():
        match = _PROMPT_LINE_RE.match(line)
        if match:
            flush()
            current = [match.group(1)]
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("-") or stripped.startswith("="):
            flush()
        else:
            current.append(line)
    flush()
    return prompts


def read_prompts() -> list[str]:
    """Intercepted agent prompts of the active session, oldest first."""
    return parse_prompts(read_notes_content())


def _parse_summary_points(raw_markdown: str | None) -> list[dict]:
    if not raw_markdown:
        return []
    points: list[dict] = []
    for line in raw_markdown.splitlines():
        row = line.strip()
        if not row or row.startswith("#") or row.startswith("<!--"):
            continue
        if row.startswith("- ") or row.startswith("* "):
            text = row[2:].strip()
        elif row and row[0].isdigit() and ". " in row:
            text = row.split(". ", 1)[1].strip()
        else:
            text = row
        if text:
            points.append({"text": text, "source": "notes"})
    return points


def read_summary_payload() -> dict:
    folder = get_active_session_folder()
    if folder is None:
        return {"points": [], "raw_markdown": None, "updated_at": None}

    raw_markdown = get_ai_summary_raw(folder)
    updated_at = get_ai_summary_mtime(folder)
    points = _parse_summary_points(raw_markdown)
    return {
        "points": points,
        "raw_markdown": raw_markdown,
        "updated_at": updated_at,
    }
