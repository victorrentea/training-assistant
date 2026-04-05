## Why

After the PDF-caching-moved-to-daemon refactoring, the participant slides list is always empty. Railway stored slides state and pushed it to participants on WS connect — but after the refactoring, that state is never populated. The architectural mistake is that Railway still owns slides state, when the daemon is now the authoritative source.

The correct design: Railway never stores slides catalog or cache status. Participants fetch slides on connect via `GET /api/slides` (already proxied to daemon). The daemon owns and serves the full slides state. WS broadcasts from the daemon handle live updates (PDF cached, etc.).

## What Changes

- Participant page fetches slides catalog + cache status via `GET /api/slides` on every WS connect, instead of waiting for Railway to push it
- Daemon populates `misc_state.slides_catalog` and `misc_state.slides_cache_status` from the catalog file (and existing cached PDFs) at startup so the REST endpoint returns real data
- Railway removes slides state from the initial WS state push (cleanup)
- Daemon continues to broadcast `slides_cache_status` updates to participants via WS when PDF cache changes

## Capabilities

### New Capabilities
- `slides-initial-sync`: Participant fetches slides on WS connect via REST; daemon is the sole source of truth for slides state

### Modified Capabilities

## Impact

- `static/participant.js` — call `_refreshSlidesCatalog()` in `ws.onopen`; also apply `data.cache_status` from REST response
- `daemon/slides/loop.py` — populate `misc_state.slides_catalog` + `misc_state.slides_cache_status` (checking on-disk PDFs) in `SlidesPollingRunner.start()`
- `railway/features/ws/router.py` — remove `_send_initial_messages()` and its call; Railway no longer owns `state.slides_cache_status`
- `tests/hermetic/` — E2E test: participant receives non-empty slides list after connecting
