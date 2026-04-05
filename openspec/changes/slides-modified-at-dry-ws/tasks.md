## 1. Daemon — expose modified_at from PPTX st_mtime

- [x] 1.1 In `daemon/slides/catalog.py` `detect_changed_files()`, store `current_mtime` as `pptx_mtime` in `tracked[key]` whenever a scan runs (even if file hasn't changed)
- [x] 1.2 In `_slides_from_state()`, add `"modified_at": _iso_utc(entry.get("pptx_mtime"))` to each slide dict
- [x] 1.3 In `_merge_slides()`, pass through `modified_at` alongside `updated_at`

## 2. Daemon — strip slides payload from slides_cache_status WS broadcast

- [x] 2.1 In `daemon/ws_messages.py`, remove the `slides` field from `SlidesCacheStatusMsg` (keep only `type`)
- [x] 2.2 In `daemon/slides/router.py` `_broadcast_slides_cache_status()`, send `SlidesCacheStatusMsg()` with no arguments (no slides data)

## 3. Participant JS — REST-refresh on slides_cache_status

- [x] 3.1 In `static/participant.js` `case 'slides_cache_status':`, replace the inline slides/cache-status merge logic with a call to the existing `GET /api/slides` fetch (same path used on initial load at line ~2352)
- [x] 3.2 After the fetch, apply the returned slides to `slidesCatalog` and `_slidesCacheStatus` using existing normalization helpers, then re-render the slides list

## 4. Participant JS — render modified_at on topic lines

- [x] 4.1 In `_buildSlideItem()`, change `_formatSlideUpdatedCompact(slide.updated_at || ...)` to use `slide.modified_at` only
- [x] 4.2 Keep `updated_at` for `_isSlideNew()` baseline tracking (tracks export changes, not source mtime)

## 5. Host JS — REST-refresh on slides_cache_status

- [x] 5.1 In `static/host.js` `else if (msg.type === 'slides_cache_status')`, replace the inline `_buildSlidesCacheStatusMapFromSlides(msg.slides || [])` + catalog update with a call to the existing `_refreshHostSlidesCatalog()` function

## 6. Update contracts and docs

- [x] 6.1 In `apis.md`, add `modified_at` to the slides[] schema description and update `slides_cache_status` WS entry to show no payload
- [x] 6.2 In `docs/participant-ws.yaml` and `docs/host-ws.yaml`, update `slides_cache_status` message schema to remove `slides` field

## 7. Periodic mtime scan (user addition)

- [x] 7.1 Add `refresh_pptx_mtimes()` to `catalog.py` — reads all PPTX `st_mtime` values, updates daemon state, returns whether anything changed
- [x] 7.2 Add `scan_pptx_mtimes()` to `SlidesRunner` (loop.py) — propagates updated `modified_at` to `misc_state.slides_cache_status`
- [x] 7.3 Add `last_slides_mtime_scan_at` periodic check in `__main__.py` — calls scan every 60s, broadcasts `slides_cache_status` if any mtime changed
