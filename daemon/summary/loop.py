"""Summary helpers: read ai-summary.md content and mtime."""

from datetime import datetime
from pathlib import Path

__all__ = [
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
