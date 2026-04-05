## Why

The host UI slide stats panel (deck names, slide counts visualized, time spent per deck) stopped displaying after the daemon architecture was refactored. The `slides_log`, `slides_log_deep_count`, and `slides_log_topic` fields that `host.js` expects were never implemented in the current daemon's `host_state_router.py`. The raw data already exists in `activity-slides-<date>.md` files on disk — the daemon just needs to parse and expose it.

## What Changes

- Add a parser that reads `activity-slides-<date>.md` and extracts per-slide time data
- Filter entries to the session's active time window (from session_meta.json), or the entire day if no session state is available
- Expose `slides_log`, `slides_log_deep_count`, and `slides_log_topic` in the daemon's host state response (`GET /{sid}/host/state`)
- No runtime event tracking, no new state fields, no changes to Railway or frontend

## Capabilities

### New Capabilities
- `slides-time-tracking`: Daemon parses the `activity-slides-<date>.md` file and exposes aggregate slide stats to the host UI, filtered to the current session's active timeframe

### Modified Capabilities
- `slides`: Host state endpoint must include slide-log stats alongside existing cache/catalog data

## Impact

- New module `daemon/slides/activity_reader.py` — parser for `activity-slides-<date>.md` files
- `daemon/host_state_router.py` — call the reader and return `slides_log`, `slides_log_deep_count`, `slides_log_topic`
- No changes to Railway backend, participant UI, or `host.js`/`host.html`
