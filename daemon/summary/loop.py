"""Summary polling loop helpers.

Key-points I/O is provided by session_state; this module re-exports for convenience
and provides the run_summary_cycle() helper used by the main orchestrator loop.
"""

from datetime import datetime
from pathlib import Path

from daemon import log
from daemon.session_state import (
    load_key_points,
    save_key_points,
)

__all__ = [
    "load_key_points",
    "save_key_points",
    "run_summary_cycle",
    "get_ai_summary_mtime",
    "get_ai_summary_raw",
]

AI_SUMMARY_FILE = "ai-summary.md"


def _read_ai_summary_raw(session_folder: Path) -> str | None:
    """Read raw content of ai-summary.md for markdown rendering."""
    ai_file = session_folder / AI_SUMMARY_FILE
    if not ai_file.exists():
        return None
    try:
        return ai_file.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def get_ai_summary_raw(session_folder: Path) -> str | None:
    """Public alias for reading raw ai-summary.md content."""
    return _read_ai_summary_raw(session_folder)


def get_ai_summary_mtime(session_folder: Path) -> str | None:
    """Return ISO-format UTC mtime of ai-summary.md, or None if not found."""
    ai_file = session_folder / AI_SUMMARY_FILE
    if not ai_file.exists():
        return None
    try:
        from datetime import timezone as _tz
        mtime = ai_file.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=_tz.utc).isoformat()
    except OSError:
        return None


def _read_ai_summary_file(session_folder: Path) -> list[dict] | None:
    """Read ai-summary.md from session folder and return as key points list.

    Returns None if file not found, empty list if file is empty.
    """
    ai_file = session_folder / AI_SUMMARY_FILE
    if not ai_file.exists():
        log.info("summarizer", f"No {AI_SUMMARY_FILE} found in {session_folder.name}")
        return None
    try:
        text = ai_file.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            return []
        points = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("<!--"):
                continue
            if line.startswith("- ") or line.startswith("* "):
                text_content = line[2:].strip()
            elif line and line[0].isdigit() and ". " in line:
                text_content = line.split(". ", 1)[1].strip()
            else:
                text_content = line
            if text_content:
                points.append({"text": text_content, "source": "notes"})
        log.info("summarizer", f"Read {len(points)} key points from {AI_SUMMARY_FILE}")
        return points
    except OSError as e:
        log.error("summarizer", f"Could not read {AI_SUMMARY_FILE}: {e}")
        return None


def run_summary_cycle(
    config,
    sessions_root: Path,
    session_name: str,
    current_key_points: list[dict],
    summary_watermark: int,
) -> tuple[list[dict], int]:
    """Run one on-demand summary generation cycle.

    Returns updated (current_key_points, summary_watermark).
    Reads ai-summary.md from session folder instead of generating via Claude API.
    Saves key points to disk on success.
    """
    session_folder = sessions_root / session_name

    # Read from ai-summary.md file in session folder
    try:
        new_points = _read_ai_summary_file(session_folder)
        if new_points is not None:
            current_key_points = new_points
            save_key_points(session_folder, current_key_points, 0)
            log.info("summarizer", f"Key points: {len(current_key_points)} total (from {AI_SUMMARY_FILE})")
    except Exception as e:
        log.error("summarizer", f"Error reading {AI_SUMMARY_FILE}: {e}")

    return current_key_points, summary_watermark
