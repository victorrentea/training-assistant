## Why

Participants have no way to see when a topic's PPTX file was last updated on the trainer's machine — the existing `updated_at`/`downloaded_at` fields reflect export/cache events, not source freshness. Additionally, `slides_cache_status` WS events currently duplicate the full slides[] payload, creating a divergence risk between WS and REST representations.

## What Changes

- Add `modified_at` field to each slide entry in `GET /{sid}/api/slides` — the raw PPTX file `st_mtime` as tracked by the daemon
- Participant UI renders `modified_at` on each topic line (replacing the existing `updated_at`-based timestamp display)
- **BREAKING**: `slides_cache_status` WS message carries no payload data — it becomes a pure invalidation signal (`{type: "slides_cache_status"}`)
- Participant and host JS handle `slides_cache_status` by calling `GET /api/slides` to refresh, eliminating the dual-path update logic

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- `slides`: Add `modified_at` field to the slides[] response schema; change `slides_cache_status` WS contract to carry no payload (trigger-only)

## Impact

- `daemon/slides/catalog.py` — expose PPTX `st_mtime` as `modified_at` in slide entries
- `daemon/ws_messages.py` — remove `slides` field from `SlidesCacheStatusMsg`
- `daemon/slides/router.py` — stop embedding slides data in `slides_cache_status` broadcasts
- `static/participant.js` — handle `slides_cache_status` as REST trigger; render `modified_at` on slide items
- `static/host.js` — handle `slides_cache_status` as REST trigger (call `/api/slides`) instead of consuming inline data
- `apis.md` — update slides[] schema and `slides_cache_status` WS contract
- `openspec/specs/slides/spec.md` — update spec to match new contracts
