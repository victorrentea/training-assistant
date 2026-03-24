"""Tests for daemon/session_transcript.py — session time-range computation."""

from datetime import datetime, date
import pytest
from daemon.session_transcript import (
    compute_active_windows,
    count_lines_in_windows,
    format_time_ranges,
    parse_txt_entries_with_datetimes,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def dt(hour, minute=0, second=0, day=24, month=3, year=2026):
    return datetime(year, month, day, hour, minute, second)


def mk_session(started: datetime, ended: datetime | None = None, paused=None) -> dict:
    s = {"name": "test-session", "started_at": started.isoformat()}
    if ended is not None:
        s["ended_at"] = ended.isoformat()
    if paused:
        s["paused_intervals"] = paused
    return s


def mk_pause(from_dt: datetime, to_dt: datetime | None = None, reason: str = "nested") -> dict:
    p = {"from": from_dt.isoformat(), "reason": reason}
    if to_dt is not None:
        p["to"] = to_dt.isoformat()
    return p


NOW = dt(17, 30)


# ─── compute_active_windows ───────────────────────────────────────────────────

class TestComputeActiveWindows:
    def test_scenario_a_single_day_no_pauses(self):
        """Single-day workshop — one continuous window."""
        s = mk_session(dt(9), dt(17, 30))
        windows = compute_active_windows(s, NOW)
        assert windows == [(dt(9), dt(17, 30))]

    def test_scenario_a_still_running(self):
        """Active session without ended_at — window ends at 'now'."""
        s = mk_session(dt(9))  # no ended_at
        windows = compute_active_windows(s, NOW)
        assert windows == [(dt(9), NOW)]

    def test_scenario_b_nested_talk_ended(self):
        """Workshop with completed nested talk — two windows, hole in the middle."""
        s = mk_session(dt(9), dt(17), paused=[mk_pause(dt(12), dt(13, 30))])
        windows = compute_active_windows(s, NOW)
        assert windows == [
            (dt(9), dt(12)),
            (dt(13, 30), dt(17)),
        ]

    def test_scenario_c_currently_inside_nested_talk(self):
        """Currently inside a nested talk (open pause) — only pre-pause window."""
        s = mk_session(dt(9), paused=[mk_pause(dt(12))])  # open pause, no to
        windows = compute_active_windows(s, NOW)
        assert windows == [(dt(9), dt(12))]

    def test_scenario_d_two_day_workshop(self):
        """Two-day workshop (same session folder) — windows on both days."""
        s = mk_session(
            dt(9, 30, day=24),
            paused=[mk_pause(dt(20, day=24), dt(9, 30, day=25), reason="day_end")],
        )
        now_day2 = dt(17, day=25)
        windows = compute_active_windows(s, now_day2)
        assert windows == [
            (dt(9, 30, day=24), dt(20, day=24)),
            (dt(9, 30, day=25), dt(17, day=25)),
        ]

    def test_scenario_e_two_day_with_nested_talk_on_day2(self):
        """Two-day workshop with a nested talk on Day 2."""
        s = mk_session(
            dt(9, 30, day=24),
            paused=[
                mk_pause(dt(20, day=24), dt(9, 30, day=25), reason="day_end"),
                mk_pause(dt(12, day=25), dt(13, day=25), reason="nested"),
            ],
        )
        now_day2 = dt(17, day=25)
        windows = compute_active_windows(s, now_day2)
        assert windows == [
            (dt(9, 30, day=24), dt(20, day=24)),
            (dt(9, 30, day=25), dt(12, day=25)),
            (dt(13, day=25), dt(17, day=25)),
        ]

    def test_multiple_pauses_ordered_correctly(self):
        """Multiple non-overlapping pauses produce correct interleaved windows."""
        s = mk_session(
            dt(9), dt(18),
            paused=[mk_pause(dt(15), dt(15, 30)), mk_pause(dt(12), dt(13))],
        )
        windows = compute_active_windows(s, NOW)
        assert windows == [
            (dt(9), dt(12)),
            (dt(13), dt(15)),
            (dt(15, 30), dt(18)),
        ]

    def test_session_still_paused_overnight(self):
        """Paused at day end, not yet resumed — window ends at pause start."""
        s = mk_session(
            dt(9, 30, day=24),
            paused=[mk_pause(dt(20, day=24), reason="day_end")],  # open
        )
        now_morning = dt(8, day=25)
        windows = compute_active_windows(s, now_morning)
        assert windows == [(dt(9, 30, day=24), dt(20, day=24))]


# ─── count_lines_in_windows ───────────────────────────────────────────────────

class TestCountLinesInWindows:
    def test_counts_only_lines_with_datetime_and_content(self):
        entries = [
            (dt(10), "Hello world"),
            (dt(11), "More text"),
            (None, "No timestamp line"),  # excluded: no datetime
            (dt(12), ""),                 # excluded: empty text
            (dt(13), "  "),              # excluded: whitespace only
        ]
        windows = [(dt(9), dt(17))]
        assert count_lines_in_windows(entries, windows) == 2

    def test_excludes_lines_outside_windows(self):
        entries = [
            (dt(8), "Too early"),
            (dt(10), "In window"),
            (dt(13), "In gap"),
            (dt(14), "In second window"),
            (dt(18), "Too late"),
        ]
        windows = [(dt(9), dt(12)), (dt(13, 30), dt(17))]
        assert count_lines_in_windows(entries, windows) == 2  # 10:00 and 14:00

    def test_empty_windows_returns_zero(self):
        entries = [(dt(10), "text")]
        assert count_lines_in_windows(entries, []) == 0

    def test_boundary_lines_are_included(self):
        entries = [
            (dt(9), "start boundary"),
            (dt(17), "end boundary"),
        ]
        windows = [(dt(9), dt(17))]
        assert count_lines_in_windows(entries, windows) == 2


# ─── format_time_ranges ───────────────────────────────────────────────────────

class TestFormatTimeRanges:
    def test_scenario_a_single_continuous_window(self):
        windows = [(dt(9, 30), dt(17, 30))]
        assert format_time_ranges(windows, 280) == "09:30–17:30 · 280 lines"

    def test_scenario_b_two_windows_same_day(self):
        windows = [(dt(9, 30), dt(12, 30)), (dt(13, 30), dt(17, 30))]
        assert format_time_ranges(windows, 250) == "09:30–12:30, 13:30–17:30 · 250 lines"

    def test_scenario_d_two_day_workshop(self):
        windows = [
            (dt(9, 30, day=24), dt(20, day=24)),
            (dt(9, 30, day=25), dt(17, day=25)),
        ]
        assert format_time_ranges(windows, 520) == "Day 1 09:30–20:00, Day 2 09:30–17:00 · 520 lines"

    def test_scenario_e_two_day_with_nested_talk_on_day2(self):
        windows = [
            (dt(9, 30, day=24), dt(20, day=24)),
            (dt(9, 30, day=25), dt(12, day=25)),
            (dt(13, day=25), dt(17, day=25)),
        ]
        assert format_time_ranges(windows, 490) == (
            "Day 1 09:30–20:00, Day 2 09:30–12:00, 13:00–17:00 · 490 lines"
        )

    def test_singular_line(self):
        windows = [(dt(10), dt(10, 5))]
        assert format_time_ranges(windows, 1) == "10:00–10:05 · 1 line"

    def test_empty_windows(self):
        result = format_time_ranges([], 0)
        assert "no transcript windows" in result

    def test_no_day_prefix_for_single_day(self):
        windows = [(dt(9), dt(12)), (dt(13), dt(17))]
        result = format_time_ranges(windows, 100)
        assert "Day" not in result


# ─── parse_txt_entries_with_datetimes ─────────────────────────────────────────

class TestParseTxtEntriesWithDatetimes:
    def test_parses_full_datetime_timestamp(self):
        text = "[2026-03-24 09:30:15.00] Speaker: Hello"
        entries = parse_txt_entries_with_datetimes(text)
        assert len(entries) == 1
        dt_val, text_val = entries[0]
        assert dt_val == datetime(2026, 3, 24, 9, 30, 15)
        assert text_val == "Speaker: Hello"

    def test_parses_time_only_with_file_date(self):
        text = "[09:30:15.00] Hello"
        entries = parse_txt_entries_with_datetimes(text, file_date=date(2026, 3, 24))
        assert len(entries) == 1
        dt_val, text_val = entries[0]
        assert dt_val == datetime(2026, 3, 24, 9, 30, 15)
        assert text_val == "Hello"

    def test_time_only_without_file_date_returns_none_dt(self):
        text = "[09:30:15.00] Hello"
        entries = parse_txt_entries_with_datetimes(text, file_date=None)
        dt_val, _ = entries[0]
        assert dt_val is None

    def test_skips_empty_lines(self):
        text = "\n\n[2026-03-24 10:00:00.00] Text\n\n"
        entries = parse_txt_entries_with_datetimes(text)
        assert len(entries) == 1

    def test_heartbeat_line_no_text(self):
        """Daemon heartbeat lines have no text after the timestamp."""
        text = "[2026-03-24 09:30:15.00] "
        entries = parse_txt_entries_with_datetimes(text)
        dt_val, text_val = entries[0]
        assert dt_val == datetime(2026, 3, 24, 9, 30, 15)
        assert text_val == ""

    def test_plain_lines_without_timestamp_get_none_dt(self):
        text = "Plain line without timestamp"
        entries = parse_txt_entries_with_datetimes(text)
        dt_val, text_val = entries[0]
        assert dt_val is None
        assert text_val == "Plain line without timestamp"

    def test_mixed_content(self):
        text = (
            "[2026-03-24 09:30:00.00] First\n"
            "Plain line\n"
            "[2026-03-24 09:31:00.00] Second\n"
        )
        entries = parse_txt_entries_with_datetimes(text)
        assert len(entries) == 3
        assert entries[0][0] == datetime(2026, 3, 24, 9, 30, 0)
        assert entries[1][0] is None
        assert entries[2][0] == datetime(2026, 3, 24, 9, 31, 0)
