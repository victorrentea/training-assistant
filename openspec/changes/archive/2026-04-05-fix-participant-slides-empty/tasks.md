## 1. Daemon: initialize slides state from catalog on startup

- [x] 1.1 In `daemon/slides/loop.py` `SlidesPollingRunner.start()`, after loading `_slides_state`, build catalog entries: for each entry from `load_catalog_entries(cfg.catalog_file)`, derive slug from `_slides_state["files"][_abs_key(entry["source"])]["slug"]` or fall back to `_slugify(Path(entry["target_pdf"]).stem)`; call `misc_state.update_slides_catalog([{"slug": slug, "title": entry["title"], "drive_export_url": entry["drive_export_url"]}, ...])`
- [x] 1.2 In the same `SlidesPollingRunner.start()`, after updating catalog, initialize `misc_state.slides_cache_status`: for each slug+entry, check if `cfg.publish_dir / entry["target_pdf"]` exists; set `misc_state.slides_cache_status[slug] = {"status": "cached" if exists else "not_cached"}` (skip slugs already in cache_status)

## 2. Participant JS: fetch slides on WS connect

- [x] 2.1 In `static/participant.js` `ws.onopen`, add `_refreshSlidesCatalog({ autoLoadSelected: true }).catch(() => {})` alongside the existing `/api/participant/state` fetch (both fire in parallel)
- [x] 2.2 In `_refreshSlidesCatalog`, after setting `slidesCatalog = _normalizeSlidesCatalog(data.slides)`, also apply `_slidesCacheStatus = data.cache_status || {}` and re-render if the slides list is already open

## 3. Railway: remove slides state push on participant connect

- [x] 3.1 In `railway/features/ws/router.py`, remove the `_send_initial_messages()` function and remove its call inside `_handle_participant_connection`

## 4. Hermetic E2E test

- [x] 4.1 In `tests/docker/`, add `test_slides_initial_sync.py`: verifies `GET /api/slides` (proxied to daemon) returns non-empty slides list with expected slugs; also verifies `cache_status` is present for each slug

## 5. Verify and push

- [x] 5.1 Run `bash tests/check-all.sh` and confirm no regressions (315 passed, 1 pre-existing failure unrelated to this change)
- [x] 5.2 Push to master and wait for production deploy confirmation (deployed after ~33s)
