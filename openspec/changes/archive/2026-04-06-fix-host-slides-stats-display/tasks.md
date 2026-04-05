## 1. Activity File Parser

- [x] 1.1 Create `daemon/slides/activity_reader.py` with a `read_slides_log(folder, date, active_intervals)` function that reads `activity-slides-<date>.md`
- [x] 1.2 Parse lines matching `HH:MM:SS DeckName - s<num>:<duration>[, ...]`; skip pointer lines (`DeckName:N`) and blank lines
- [x] 1.3 Parse durations in `XmYs`, `Xm`, or `Ys` notation into integer seconds
- [x] 1.4 Keep last-wins per `(timestamp_str, deck)` pair; merge into a flat `list[dict]` of `{file, slide, seconds_spent}`
- [x] 1.5 Filter entries by `active_intervals` (if provided): include only entries whose `HH:MM:SS` is ≥ session `started_at` and not inside a closed pause interval; if `active_intervals` is `None`, include all entries

## 2. Host State Router — Expose Slides Log Fields

- [x] 2.1 In `daemon/host_state_router.py`, determine the session's active intervals from the current `session_stack` (use `session_stack[0]["started_at"]` and `session_stack[0]["paused_intervals"]` if available, else pass `None`)
- [x] 2.2 Call `read_slides_log(config.folder, date.today(), active_intervals)` and assign result to `slides_log`
- [x] 2.3 Add `slides_log`, `slides_log_deep_count` (`len({(e['file'],e['slide']) for e in slides_log})`), and `slides_log_topic` to the host state response dict (after `slides_current` around line 182)
- [x] 2.4 Derive `slides_log_topic`: use `misc_state.slides_current['presentation_name']` if set, else `file` of the max-`seconds_spent` entry, else `None`

## 3. Verification

- [x] 3.1 Unit-test `read_slides_log` in `tests/`: parse sample lines, verify duration parsing, verify last-wins, verify session time filtering
- [x] 3.2 Start the daemon locally and call `GET /host/state`; confirm `slides_log`, `slides_log_deep_count`, `slides_log_topic` appear with correct values matching the activity file
- [x] 3.3 Open the host UI, hover the slides-log badge, confirm the popover shows deck names, slide counts, and formatted time totals
- [x] 3.4 Run `bash tests/check-all.sh` and confirm no regressions (2 pre-existing failures unrelated to this change)
