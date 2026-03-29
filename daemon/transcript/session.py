"""Transcript time-range computation for session-aware startup logging.

Computes the active time windows for a session (excluding nested-session holes
and day-end pauses), counts transcript lines within those windows, and formats
a human-readable summary for the daemon startup log.
"""

import re
from datetime import datetime, date
from typing import Optional


# Matches full datetime timestamps: [2026-03-24 09:30:15.00] text
_DATETIME_TS_RE = re.compile(
    r"^\[\s*(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})\.\d*\s*\]\s*(.*)"
)
# Matches time-only timestamps: [09:30:15.00] text
_TIME_ONLY_TS_RE = re.compile(r"^\[\s*(\d{2}):(\d{2}):(\d{2})\.\d*\s*\]\s*(.*)")


def parse_txt_entries_with_datetimes(
    text: str, file_date: Optional[date] = None
) -> list[tuple[Optional[datetime], str]]:
    """Parse a .txt transcript into (datetime|None, text) entries.

    Entries without a recognisable timestamp get dt=None.
    Time-only timestamps are resolved against *file_date* when provided.
    Empty lines are skipped.
    """
    entries: list[tuple[Optional[datetime], str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _DATETIME_TS_RE.match(line)
        if m:
            try:
                dt = datetime(
                    int(m.group(1)), int(m.group(2)), int(m.group(3)),
                    int(m.group(4)), int(m.group(5)), int(m.group(6)),
                )
                entries.append((dt, m.group(7).strip()))
                continue
            except ValueError:
                pass
        if file_date:
            m2 = _TIME_ONLY_TS_RE.match(line)
            if m2:
                try:
                    dt = datetime(
                        file_date.year, file_date.month, file_date.day,
                        int(m2.group(1)), int(m2.group(2)), int(m2.group(3)),
                    )
                    entries.append((dt, m2.group(4).strip()))
                    continue
                except ValueError:
                    pass
        entries.append((None, line))
    return entries


def compute_active_windows(
    session: dict, now: datetime
) -> list[tuple[datetime, datetime]]:
    """Return the list of (start, end) active time windows for a session.

    Paused intervals (nested sessions, day-end, explicit) are excluded.
    An open (un-closed) pause means the session is currently paused — the
    window that started before the pause is still emitted, but nothing after.
    """
    started_at = datetime.fromisoformat(session["started_at"])
    ended_at = (
        datetime.fromisoformat(session["ended_at"])
        if session.get("ended_at")
        else now
    )
    paused = sorted(
        session.get("paused_intervals", []), key=lambda p: p["from"]
    )

    windows: list[tuple[datetime, datetime]] = []
    cursor = started_at

    for pause in paused:
        pause_from = datetime.fromisoformat(pause["from"])
        pause_to_str = pause.get("to")

        if pause_from > cursor:
            windows.append((cursor, pause_from))

        if pause_to_str:
            cursor = datetime.fromisoformat(pause_to_str)
        else:
            # Still paused — no further active windows
            return windows

    if cursor < ended_at:
        windows.append((cursor, ended_at))
    return windows


def count_lines_in_windows(
    entries: list[tuple[Optional[datetime], str]],
    windows: list[tuple[datetime, datetime]],
) -> int:
    """Count transcript entries with non-empty content that fall within windows."""
    if not windows:
        return 0
    count = 0
    for dt, text in entries:
        if dt is None or not text.strip():
            continue
        for start, end in windows:
            if start <= dt <= end:
                count += 1
                break
    return count


def format_time_ranges(
    windows: list[tuple[datetime, datetime]], line_count: int
) -> str:
    """Format active windows as a human-readable startup-log string.

    Single-day examples:
        "09:30–17:30 · 280 lines"
        "09:30–12:30, 13:30–17:30 · 250 lines"

    Multi-day examples:
        "Day 1 09:30–17:30, Day 2 09:00–17:00 · 520 lines"
        "Day 1 09:30–17:30, Day 2 09:00–12:00, 13:00–17:00 · 490 lines"
    """
    if not windows:
        return f"no transcript windows · {line_count} lines"

    session_start_date: date = windows[0][0].date()
    all_dates = {w[0].date() for w in windows}
    is_multi_day = len(all_dates) > 1

    parts: list[str] = []
    last_date: Optional[date] = None

    for start, end in windows:
        d = start.date()
        prefix = ""
        if is_multi_day and d != last_date:
            day_n = (d - session_start_date).days + 1
            prefix = f"Day {day_n} "
            last_date = d
        parts.append(f"{prefix}{start.strftime('%H:%M')}–{end.strftime('%H:%M')}")

    lines_label = "line" if line_count == 1 else "lines"
    return f"{', '.join(parts)} · {line_count} {lines_label}"


def format_startup_log(
    entries: list[tuple[Optional[datetime], str]],
    windows: list[tuple[datetime, datetime]],
    summary_watermark: int,
    is_ongoing: bool,
    session_start_date: date,
    today: date,
) -> str:
    """Format the startup transcript log line.

    Example output:
        Unprocessed: 100 lines since 12:11 / 174 during [09:30-12:30, 13:30-now...
        Unprocessed: 50 lines since Day 1 17:00 / 120 during [Day 1 09:30-17:00] [09:00-now...
        Unprocessed: 100 lines since — / 100 during [09:30-now...
    """
    def _fmt_dt(dt: datetime) -> str:
        d = dt.date()
        hm = dt.strftime("%H:%M")
        if d == today:
            return hm
        day_n = (d - session_start_date).days + 1
        return f"Day {day_n} {hm}"

    non_empty = [(dt, txt) for dt, txt in entries if dt is not None and txt.strip()]

    # Watermark
    if summary_watermark == 0 or summary_watermark > len(non_empty):
        watermark_str = "—"
    else:
        watermark_dt = non_empty[summary_watermark - 1][0]
        watermark_str = _fmt_dt(watermark_dt)

    # Counts
    total_lines = len(non_empty)
    session_lines = count_lines_in_windows(non_empty, windows)

    # Segments — group same-day windows into one bracket
    if not windows:
        during = ""
    else:
        # Group consecutive windows by date
        day_groups: list[list[tuple[int, datetime, datetime]]] = []
        current_day = None
        current_group: list[tuple[int, datetime, datetime]] = []
        for i, (start, end) in enumerate(windows):
            d = start.date()
            if d != current_day:
                if current_group:
                    day_groups.append(current_group)
                current_day = d
                current_group = [(i, start, end)]
            else:
                current_group.append((i, start, end))
        if current_group:
            day_groups.append(current_group)

        last_idx = len(windows) - 1
        parts = []
        for group in day_groups:
            segments = []
            for j, (i, start, end) in enumerate(group):
                start_str = _fmt_dt(start) if j == 0 else start.strftime("%H:%M")
                if i == last_idx and is_ongoing:
                    segments.append(f"{start_str}-now...")
                else:
                    segments.append(f"{start_str}-{end.strftime('%H:%M')}")
            inner = ", ".join(segments)
            is_last_group = group is day_groups[-1]
            if is_last_group and is_ongoing:
                parts.append(f"[{inner}")
            else:
                parts.append(f"[{inner}]")
        during = " during " + " ".join(parts)

    return f"Unprocessed: {session_lines} lines since {watermark_str} / {total_lines} lines{during}"
