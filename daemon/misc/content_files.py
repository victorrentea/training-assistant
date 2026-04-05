"""Session notes/summary readers from active session folder on disk."""
from __future__ import annotations

from pathlib import Path

from daemon.session import state as session_shared_state
from daemon.session_state import find_notes_in_folder
from daemon.summary.loop import get_ai_summary_mtime, get_ai_summary_raw

AI_SUMMARY_FILE = "ai-summary.md"


def get_active_session_folder() -> Path | None:
    root = session_shared_state.get_sessions_root()
    stack = session_shared_state.get_session_stack()
    if root is None or not stack:
        return None
    name = stack[-1].get("name")
    if not name:
        return None
    folder = root / str(name)
    if not folder.exists() or not folder.is_dir():
        return None
    return folder


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


def _parse_summary_points(raw_markdown: str | None) -> list[dict]:
    if not raw_markdown:
        return []
    points: list[dict] = []
    for line in raw_markdown.splitlines():
        row = line.strip()
        if not row or row.startswith("#"):
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
