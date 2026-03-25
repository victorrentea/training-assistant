# Transcript Startup Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current single-line startup transcript log with a richer format showing the summarizer watermark, unprocessed line count, session line count, and active time segments with `now...` for live sessions.

**Architecture:** Add `format_startup_log()` to `daemon/session_transcript.py` (pure formatting, no session dict coupling). Update the startup block in `training_daemon.py` to compute `is_ongoing` and call the new function instead of `format_time_ranges`.

**Tech Stack:** Python 3.12, `datetime`/`date` stdlib, pytest

---

## File Map

- **Modify:** `daemon/session_transcript.py` — add `format_startup_log()` function
- **Modify:** `training_daemon.py:567-571` — replace `format_time_ranges` call with `format_startup_log`
- **Modify:** `tests/test_session_transcript.py` — add `TestFormatStartupLog` class

---

### Task 1: Write failing tests for `format_startup_log`

**Files:**
- Modify: `tests/test_session_transcript.py`

- [ ] **Step 1: Add import for `format_startup_log` and write the test class**

Open `tests/test_session_transcript.py`. Add `format_startup_log` to the existing import:

```python
from daemon.session_transcript import (
    compute_active_windows,
    count_lines_in_windows,
    format_time_ranges,
    format_startup_log,
    parse_txt_entries_with_datetimes,
)
```

Then append this class at the bottom of the file:

```python
# ─── format_startup_log ───────────────────────────────────────────────────────

TODAY = date(2026, 3, 24)
SESSION_START_DATE = date(2026, 3, 24)


def make_entries(*times_and_texts):
    """Helper: list of (datetime|None, str) tuples."""
    return list(times_and_texts)


class TestFormatStartupLog:
    """
    format_startup_log(entries, windows, summary_watermark, is_ongoing,
                       session_start_date, today) -> str
    """

    def test_active_session_today_no_watermark(self):
        """Fresh session: watermark=0, one segment ending with now..."""
        entries = [
            (dt(9, 30), "Hello"),
            (dt(9, 45), "World"),
            (dt(10, 0), "More"),
        ]
        windows = [(dt(9, 30), dt(10, 0))]
        result = format_startup_log(
            entries, windows,
            summary_watermark=0,
            is_ongoing=True,
            session_start_date=SESSION_START_DATE,
            today=TODAY,
        )
        assert result == "Watermark: —, Unprocessed: 3 lines, session: 3 lines during [09:30-now..."

    def test_active_session_with_watermark(self):
        """Watermark covers first 2 entries; 1 unprocessed; session ongoing."""
        entries = [
            (dt(9, 30), "Hello"),
            (dt(9, 45), "World"),
            (dt(10, 0), "New"),
        ]
        windows = [(dt(9, 30), dt(10, 0))]
        result = format_startup_log(
            entries, windows,
            summary_watermark=2,
            is_ongoing=True,
            session_start_date=SESSION_START_DATE,
            today=TODAY,
        )
        assert result == "Watermark: 09:45, Unprocessed: 1 lines, session: 3 lines during [09:30-now..."

    def test_ended_session_today(self):
        """Session has ended; last segment closes at ended_at, no now..."""
        entries = [
            (dt(9, 30), "A"),
            (dt(12, 0), "B"),
        ]
        windows = [(dt(9, 30), dt(12, 0))]
        result = format_startup_log(
            entries, windows,
            summary_watermark=2,
            is_ongoing=False,
            session_start_date=SESSION_START_DATE,
            today=TODAY,
        )
        assert result == "Watermark: 12:00, Unprocessed: 0 lines, session: 2 lines during [09:30-12:00]"

    def test_two_segments_with_pause(self):
        """Session paused and resumed — two segments, ongoing."""
        entries = [
            (dt(9, 30), "A"),
            (dt(11, 0), "B"),
            (dt(13, 30), "C"),
        ]
        windows = [
            (dt(9, 30), dt(12, 0)),
            (dt(13, 30), dt(14, 0)),
        ]
        result = format_startup_log(
            entries, windows,
            summary_watermark=0,
            is_ongoing=True,
            session_start_date=SESSION_START_DATE,
            today=TODAY,
        )
        assert result == "Watermark: —, Unprocessed: 3 lines, session: 3 lines during [09:30-12:00] [13:30-now..."

    def test_previous_day_watermark_and_segment(self):
        """Multi-day: watermark and first segment are on Day 1 (previous day)."""
        day1 = date(2026, 3, 24)
        day2 = date(2026, 3, 25)
        entries = [
            (datetime(2026, 3, 24, 9, 30), "Day1 line"),
            (datetime(2026, 3, 25, 9, 0), "Day2 line"),
        ]
        windows = [
            (datetime(2026, 3, 24, 9, 30), datetime(2026, 3, 24, 17, 0)),
            (datetime(2026, 3, 25, 9, 0), datetime(2026, 3, 25, 10, 0)),
        ]
        result = format_startup_log(
            entries, windows,
            summary_watermark=1,
            is_ongoing=True,
            session_start_date=day1,
            today=day2,
        )
        assert result == (
            "Watermark: Day 1 09:30, Unprocessed: 1 lines, session: 2 lines during "
            "[Day 1 09:30-Day 1 17:00] [09:00-now..."
        )

    def test_entries_with_none_timestamps_excluded_from_counts(self):
        """Non-timed entries (dt=None) and empty-text entries don't count."""
        entries = [
            (dt(9, 30), "Real line"),
            (None, "No timestamp"),        # excluded
            (dt(9, 45), ""),              # excluded: empty text
            (dt(10, 0), "  "),            # excluded: whitespace
            (dt(10, 15), "Another line"),
        ]
        windows = [(dt(9, 0), dt(17, 0))]
        result = format_startup_log(
            entries, windows,
            summary_watermark=1,
            is_ongoing=False,
            session_start_date=SESSION_START_DATE,
            today=TODAY,
        )
        assert result == "Watermark: 09:30, Unprocessed: 1 lines, session: 2 lines during [09:00-17:00]"

    def test_no_windows(self):
        """Edge: no active windows at all."""
        result = format_startup_log(
            [], [],
            summary_watermark=0,
            is_ongoing=False,
            session_start_date=SESSION_START_DATE,
            today=TODAY,
        )
        assert "Watermark: —" in result
        assert "Unprocessed: 0 lines" in result
        assert "session: 0 lines" in result
        assert "during" not in result
```

- [ ] **Step 2: Run the tests to confirm they fail with ImportError**

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/san-juan-v2
python -m pytest tests/test_session_transcript.py::TestFormatStartupLog -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'format_startup_log'`

---

### Task 2: Implement `format_startup_log` in `daemon/session_transcript.py`

**Files:**
- Modify: `daemon/session_transcript.py`

- [ ] **Step 1: Add `format_startup_log` after `format_time_ranges`**

Open `daemon/session_transcript.py`. Append this function after line 153 (after `format_time_ranges`):

```python


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
        Watermark: 12:11, Unprocessed: 74 lines, session: 100 lines during [9:30-12:30] [13:30-now...
        Watermark: Day 1 17:00, Unprocessed: 12 lines, session: 50 lines during [Day 1 9:30-17:00] [9:00-now...
        Watermark: —, Unprocessed: 100 lines, session: 100 lines during [9:30-now...
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
    if summary_watermark == 0:
        watermark_str = "—"
    else:
        watermark_dt = non_empty[summary_watermark - 1][0]
        watermark_str = _fmt_dt(watermark_dt)

    # Counts
    unprocessed = len(non_empty) - summary_watermark
    session_lines = count_lines_in_windows(non_empty, windows)

    # Segments
    if not windows:
        during = ""
    else:
        parts = []
        for i, (start, end) in enumerate(windows):
            start_str = _fmt_dt(start)
            is_last = (i == len(windows) - 1)
            if is_last and is_ongoing:
                parts.append(f"[{start_str}-now...")
            else:
                end_str = _fmt_dt(end)
                parts.append(f"[{start_str}-{end_str}]")
        during = " during " + " ".join(parts)

    return f"Watermark: {watermark_str}, Unprocessed: {unprocessed} lines, session: {session_lines} lines{during}"
```

- [ ] **Step 2: Run the tests to confirm they pass**

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/san-juan-v2
python -m pytest tests/test_session_transcript.py::TestFormatStartupLog -v
```

Expected: All 8 tests PASS.

- [ ] **Step 3: Run the full test suite to confirm no regressions**

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/san-juan-v2
python -m pytest tests/test_session_transcript.py -v
```

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add daemon/session_transcript.py tests/test_session_transcript.py
git commit -m "feat: add format_startup_log to session_transcript"
```

---

### Task 3: Update the startup block in `training_daemon.py`

**Files:**
- Modify: `training_daemon.py:566-574`

- [ ] **Step 1: Add `format_startup_log` to the import in `training_daemon.py`**

Find the import line near the top of `training_daemon.py` that imports from `daemon.session_transcript`. It looks like:

```python
from daemon.session_transcript import (
    compute_active_windows,
    count_lines_in_windows,
    format_time_ranges,
    parse_txt_entries_with_datetimes,
)
```

Add `format_startup_log` to the list:

```python
from daemon.session_transcript import (
    compute_active_windows,
    count_lines_in_windows,
    format_startup_log,
    format_time_ranges,
    parse_txt_entries_with_datetimes,
)
```

- [ ] **Step 2: Replace the startup log block (lines ~567-571)**

Find this block in `training_daemon.py`:

```python
            if session_stack:
                current_session = session_stack[-1]
                windows = compute_active_windows(current_session, datetime.now())
                line_count = count_lines_in_windows(entries, windows)
                log.info("transcript", format_time_ranges(windows, line_count))
            else:
```

Replace it with:

```python
            if session_stack:
                current_session = session_stack[-1]
                now = datetime.now()
                windows = compute_active_windows(current_session, now)
                is_ongoing = (
                    current_session.get("ended_at") is None
                    and not any(not p.get("to") for p in current_session.get("paused_intervals", []))
                )
                log.info("transcript", format_startup_log(
                    entries, windows, summary_watermark, is_ongoing,
                    _session_start_date(current_session) or now.date(),
                    now.date(),
                ))
            else:
```

- [ ] **Step 3: Verify the daemon starts without errors**

Run the daemon briefly to confirm the new log line appears at startup (interrupt with Ctrl+C after startup):

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/san-juan-v2
python training_daemon.py 2>&1 | head -20
```

Expected: A log line like:
```
[transcript] info    Watermark: 09:30, Unprocessed: 12 lines, session: 46 lines during [09:30-now...
```
(exact values will vary)

- [ ] **Step 4: Commit**

```bash
git add training_daemon.py
git commit -m "feat: replace format_time_ranges with format_startup_log at startup"
```

---

## Done Criteria

- [ ] `format_startup_log` is exported from `daemon/session_transcript.py`
- [ ] All 8 new tests in `TestFormatStartupLog` pass
- [ ] No regressions in existing `TestFormatTimeRanges`, `TestComputeActiveWindows`, `TestCountLinesInWindows`, `TestParseTxtEntriesWithDatetimes`
- [ ] Daemon startup log shows the new format with watermark, unprocessed count, session lines, and segments
- [ ] `format_time_ranges` function is NOT removed (still used/tested elsewhere)
