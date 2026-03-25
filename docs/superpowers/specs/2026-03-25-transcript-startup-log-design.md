# Transcript Startup Log — Design Spec

**Date:** 2026-03-25
**Status:** Approved

---

## Goal

Replace the current minimal transcript stats line (`46 lines, latest=36h58m`) with a richer one-time startup log that shows:
- how far the summarizer has processed (watermark)
- how many lines are still unprocessed
- total session lines and the active time segments the session covered

---

## Output Format

```
Watermark: 12:11, Unprocessed: 74 lines, session: 100 lines during [9:30-12:30] [13:30-now...
```

Multi-day example (daemon started on Day 2):
```
Watermark: Day 1 17:00, Unprocessed: 12 lines, session: 50 lines during [Day 1 9:30-12:30] [Day 1 13:30-17:30] [9:00-now...
```

Fresh session (nothing summarised yet):
```
Watermark: —, Unprocessed: 100 lines, session: 100 lines during [9:30-now...
```

---

## Fields

### Watermark
The timestamp of the last transcript entry that has been processed by the summariser.

- Source: `entries[summary_watermark - 1]` (the last entry included in the watermark count).
- If `summary_watermark == 0`: display `—`.
- **Day N rule:** compute `watermark_date` from the timestamp seconds.
  - If `watermark_date == today` → show `HH:MM` only.
  - If `watermark_date < today` → show `Day N HH:MM` where N = `(watermark_date − session_start_date).days + 1`.

### Unprocessed
`len(non_empty_session_entries) − summary_watermark`

Non-empty entries are those with a non-None timestamp and non-blank text, filtered to the current session's time window.

### Session lines
Count of non-empty transcript entries whose timestamp falls within `[session.started_at, session.ended_at or now]`.

### Segments (the `during [...]` part)
Computed from `session_stack[-1]` (the topmost active session — may be a talk sub-session if the daemon starts mid-talk).

Algorithm:
1. Start at `session["started_at"]`.
2. Walk `session.get("paused_intervals", [])` in chronological order.
3. Each interval `{from, to}` closes the current segment at `from` and opens a new one at `to` (if `to` is not None).
4. After all intervals, close the final segment at `session["ended_at"]` if set, otherwise append `now...`.

**Segment time format:**
- Compute `segment_date` for each boundary timestamp (same seconds → date logic as watermark).
- If `segment_date == today` → `HH:MM`.
- If `segment_date < today` → `Day N HH:MM`.
- Last open segment: replace closing time with `now...` (no Day N needed for the open end).

---

## Implementation

### New helper function

```python
def _format_transcript_startup_log(
    entries: list,
    session: dict,
    summary_watermark: int,
    now: datetime,
) -> str:
```

Located in `training_daemon.py` (near other session helpers).

**Inputs:**
- `entries` — full list of `(ts, txt)` tuples from `load_transcription_files()`
- `session` — `session_stack[-1]`
- `summary_watermark` — integer watermark loaded from `_load_key_points()`
- `now` — `datetime.now()` at startup

**Returns:** the formatted log string.

### Call site

Called **once at startup**, after `_load_key_points()` and the initial `load_transcription_files()` call, before the main daemon loop begins. Log via `log.info("transcript", ...)`.

The existing 10-second periodic stats push (`_post_json /api/transcript-status`) is **unchanged**.

---

## Day N Computation Helper

```python
def _ts_to_display_time(ts_secs: float, session_start_date: date, today: date) -> str:
    """Format a timestamp (seconds) as HH:MM or 'Day N HH:MM'."""
    day_offset = int(ts_secs) // 86400
    ts_date = session_start_date + timedelta(days=day_offset)
    hh = (int(ts_secs) % 86400) // 3600
    mm = (int(ts_secs) % 3600) // 60
    time_str = f"{hh:02d}:{mm:02d}"
    if ts_date == today:
        return time_str
    day_n = (ts_date - session_start_date).days + 1
    return f"Day {day_n} {time_str}"
```

---

## Edge Cases

| Situation | Behaviour |
|-----------|-----------|
| `summary_watermark == 0` | Watermark shows `—` |
| No `paused_intervals` | Single segment: `[start-now...]` or `[start-ended_at]` |
| Session already ended | Last segment closes at `ended_at`, no `now...` |
| Daemon starts mid-talk | Uses talk's `started_at` and its own `paused_intervals` only |
| Timestamp spans midnight | Day N prefix applied per boundary; `now...` has no Day N |
| No timed entries in session window | `session: 0 lines during [...]` — segments still shown from session metadata |

---

## Out of Scope

- Changing the periodic 10-second transcript stats push format.
- Showing segments from parent sessions when a talk is active.
- Retroactively updating the log line (it is printed once and never refreshed).
