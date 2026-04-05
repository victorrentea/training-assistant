"""Parse activity-slides-<date>.md files to extract per-slide time data.

File format (one or more lines per activity period):
    HH:MM:SS DeckName.pptx - s<num>:<duration>[, s<num>:<duration> ...]
    DeckName.pptx:<current_slide>   ← pointer line, ignored here

Duration notation: XmYs, Xm, Ys (e.g. 86m7s, 13s, 2m, 1436m27s).
The last occurrence of each (timestamp, deck) pair is authoritative.
"""
import re
from datetime import date, datetime, time
from pathlib import Path

_LINE_RE = re.compile(r"^(\d{2}:\d{2}:\d{2})\s+(.+?)\s+-\s+(.+)$")
_SLIDE_RE = re.compile(r"s(\d+):(\S+?)(?:,|$)")
_DUR_RE = re.compile(r"^(?:(\d+)m)?(?:(\d+)s)?$")


def _parse_seconds(duration: str) -> int:
    """Convert 'XmYs', 'Xm', 'Ys' into total seconds."""
    m = _DUR_RE.match(duration.strip())
    if not m:
        return 0
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)


def _parse_slides(slides_str: str) -> dict[int, int]:
    """Parse 's59:86m7s, s60:13s' into {slide_num: seconds}."""
    return {
        int(m.group(1)): _parse_seconds(m.group(2))
        for m in _SLIDE_RE.finditer(slides_str)
    }


def _should_include(entry_dt: datetime, session_entry: dict) -> bool:
    """Return True if entry_dt is within the session's active (non-paused) window."""
    started_at_str = session_entry.get("started_at")
    if started_at_str:
        try:
            if entry_dt < datetime.fromisoformat(started_at_str):
                return False
        except (ValueError, TypeError):
            pass

    for pause in session_entry.get("paused_intervals", []):
        p_from_str = pause.get("from")
        p_to_str = pause.get("to")
        if not p_from_str or not p_to_str:
            continue  # open pause — not a complete closed interval
        try:
            if datetime.fromisoformat(p_from_str) <= entry_dt < datetime.fromisoformat(p_to_str):
                return False
        except (ValueError, TypeError):
            pass

    return True


def read_slides_log(
    folder: Path,
    session_date: date,
    session_entry: dict | None,
) -> list[dict]:
    """Read activity-slides-<date>.md and return a flat slides log.

    Args:
        folder: TRANSCRIPTION_FOLDER path.
        session_date: The date to read (use date.today() for active sessions).
        session_entry: session_stack[0] dict with 'started_at' and
            'paused_intervals'; pass None to include all entries from the file.

    Returns:
        List of {file, slide, seconds_spent} dicts.
    """
    activity_file = folder / f"activity-slides-{session_date.isoformat()}.md"
    if not activity_file.exists():
        return []

    try:
        lines = activity_file.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    # last-wins per (timestamp_str, deck) — cumulative updates overwrite older ones
    periods: dict[tuple[str, str], dict[int, int]] = {}

    for line in lines:
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        timestamp_str, deck, slides_str = m.group(1), m.group(2), m.group(3)

        if session_entry is not None:
            h, mi, s = timestamp_str.split(":")
            entry_dt = datetime.combine(session_date, time(int(h), int(mi), int(s)))
            if not _should_include(entry_dt, session_entry):
                continue

        periods[(timestamp_str, deck)] = _parse_slides(slides_str)

    # Flatten into slides_log entries
    return [
        {"file": deck, "slide": slide_num, "seconds_spent": seconds}
        for (_, deck), slides in periods.items()
        for slide_num, seconds in slides.items()
    ]
