# Transcript Startup Log — Design Spec

**Date:** 2026-03-25
**Status:** Approved

---

## Goal

Replace the current startup transcript log line (produced by `format_time_ranges`) with a richer format that adds the summarizer watermark, unprocessed-line count, and the active session segments shown as bracket-separated ranges.

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

Session already ended:
```
Watermark: 17:00, Unprocessed: 0 lines, session: 250 lines during [9:30-12:30] [13:30-17:30]
```

---

## Entry Type

All transcript entries used in this feature are `(datetime|None, str)` tuples produced by
`parse_txt_entries_with_datetimes()` from `daemon/session_transcript.py`.
This is what the existing startup block already uses (line ~567 of `training_daemon.py`).

---

## Fields

### Non-empty timed entries (base filter)

Filter the raw `entries` list once at the top of the helper:

```python
non_empty = [(dt, txt) for dt, txt in entries if dt is not None and txt.strip()]
```

All three counts below operate on `non_empty`.

---

### Watermark

The wall-clock time of the last transcript entry included in the summarizer watermark.

- Source: `non_empty[summary_watermark - 1][0]` — a `datetime` object.
- If `summary_watermark == 0`: display `—`.
- **Day N rule:**
  - `watermark_date = watermark_dt.date()`
  - If `watermark_date == today` → `HH:MM`
  - If `watermark_date < today` → `Day N HH:MM` where N = `(watermark_date − session_start_date).days + 1`
  - `session_start_date` comes from `_session_start_date(session)` (existing helper, line ~174 of `training_daemon.py`)

### Unprocessed lines

```python
unprocessed = len(non_empty) - summary_watermark
```

### Session lines

Count of `non_empty` entries that fall within the session's active windows:

```python
session_lines = count_lines_in_windows(non_empty, windows)
```

where `windows = compute_active_windows(session, now)` — both already exist in `daemon/session_transcript.py`.

---

### Segments (the `during [...]` part)

Use `compute_active_windows(session, now)` to get the list of `(start_dt, end_dt)` tuples.

**Open session detection** (determines whether the last segment shows `now...`):

```python
is_ongoing = (
    session.get("ended_at") is None
    and not any(not p.get("to") for p in session.get("paused_intervals", []))
)
```

If `is_ongoing` is True, replace the last window's end display with `now...`.

**Segment time formatting:**

For each boundary `dt: datetime`:
- `dt_date = dt.date()`
- If `dt_date == today` → `HH:MM`
- If `dt_date < today` → `Day N HH:MM` where N = `(dt_date − session_start_date).days + 1`

The open-end `now...` has no Day N prefix.

---

## Implementation

### New function in `daemon/session_transcript.py`

```python
def format_startup_log(
    entries: list[tuple[Optional[datetime], str]],
    windows: list[tuple[datetime, datetime]],
    summary_watermark: int,
    is_ongoing: bool,
    session_start_date: date,
    today: date,
) -> str:
```

Takes pre-computed `windows` (from `compute_active_windows`) so it does not need to know
the session dict directly. `is_ongoing` is computed at the call site (see above).

**Rationale for placing in `session_transcript.py`:** it is pure formatting over entries and
windows, which is exactly the existing module's scope. The existing `format_time_ranges`
remains in the module (it is tested separately); the new function replaces its call at startup.

### Call site changes in `training_daemon.py`

Replace the block at lines ~568–572:

```python
# Before:
windows = compute_active_windows(current_session, datetime.now())
line_count = count_lines_in_windows(entries, windows)
log.info("transcript", format_time_ranges(windows, line_count))

# After:
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
```

`summary_watermark` is already in scope from the earlier `_load_key_points()` call.

The no-session fallback path (else branch, line ~573) is unchanged.

---

## Edge Cases

| Situation | Behaviour |
|-----------|-----------|
| `summary_watermark == 0` | Watermark shows `—` |
| No `paused_intervals` | Single segment: `[start-now...]` or `[start-end]` |
| Session already ended (`ended_at` set) | Last segment closes at `ended_at`; no `now...` |
| Session currently paused (open pause) | `is_ongoing = False`; last segment closes at pause start |
| Daemon starts mid-talk | `session_stack[-1]` is the talk; only its time window and pauses are used |
| Segment or watermark on today | No Day N prefix, just `HH:MM` |
| Segment start on a previous day | `Day N HH:MM` prefix |
| No timed entries in session window | `session: 0 lines during [...]`; segments from metadata only |
| `session_stack` empty | Existing fallback unchanged: `"{N} lines (no active session)"` |
| `_session_start_date` returns None | Fall back to `now.date()` as Day 1 anchor |

---

## Out of Scope

- Changing the periodic 10-second transcript stats push (`/api/transcript-status`).
- Showing segments from parent sessions when a talk is active.
- Retroactively refreshing the log line after startup.
- Modifying or removing `format_time_ranges` (it stays; this is an additive change).
