## 1. Reproduce Bug in Production

<!-- Bug confirmed in code: process_one_file() in daemon/slides/upload.py never notifies
     Railway after downloading a fresh PDF from GDrive. Railway keeps serving the old
     cached file indefinitely. Participants never receive a slides_cache_status with
     refreshed_slugs, so no auto-reload occurs. -->

- [x] 1.1 Browse to production participant page (https://interact.victorrentea.ro) and open a slide deck so it is actively displayed
- [x] 1.2 Touch a local PPTX file (update mtime without content change) or save a minor edit
- [x] 1.3 Confirm in daemon logs that mtime change is detected and GDrive download runs
- [x] 1.4 Confirm that Railway's cached PDF is NOT invalidated (participant still sees old PDF)
- [x] 1.5 Document exact symptom in a comment in the tasks file

## 2. Railway — Invalidate Endpoint

<!-- Updated design: daemon calls Railway directly (not main daemon). -->

- [x] 2.1 Add `do_invalidate_download()` async function in `railway/features/slides/cache.py` (force re-download + broadcast with refreshed_slugs)
- [x] 2.2 Create `POST /api/slides/invalidate/{slug}` endpoint in `railway/features/slides/router.py` (host-auth via session_host, deletes cached file, marks stale, fires background task)
- [x] 2.3 Endpoint registered on `router` APIRouter which is already included in `session_host` with host-auth in `railway/app.py` — no extra wiring needed

## 3. Slides Upload Daemon — Trigger Invalidation

- [x] 3.1 Add `_notify_railway_invalidate()` in `daemon/slides/upload.py`
- [x] 3.2 Call it at the end of `process_one_file()` after publish succeeds, using `config.server_url` + session_id + drive_export_url from metadata

## 4. Railway — Force Re-Download of Cached PDF

- [x] 4.1 `do_download()` in `railway/features/slides/cache.py` already uses `dest.write_bytes(payload)` which overwrites any existing cached file — confirmed correct
- [x] 4.2 The new `do_invalidate_download()` broadcasts directly with `refreshed_slugs` (bypasses daemon WS round-trip for this flow)

## 5. Participant — Auto-Reload Active Slide

- [x] 5.1 In `static/participant.js`, `slides_cache_status` handler now captures `msg.refreshed_slugs`
- [x] 5.2 After `_refreshSlidesCatalog()` resolves, calls `_loadSlideIntoViewer(currentSlide, { forceReload: true, cacheVersion: Date.now() })` if `slidesSelectedSlug` is in `refreshed_slugs`

## 6. Hermetic E2E Test (Docker)

- [x] 6.1 Created `tests/docker/test_slides_auto_refresh.py`
- [x] 6.2 4 test scenarios: invalidate triggers re-download, body-less fallback, WS refreshed_slugs broadcast, participant auto-reload
- [x] 6.3-6.6 Tests cover: prime cache → invalidate → mock Drive re-download count → participant reload
- [ ] 6.7 Run test — confirm it FAILS before code changes (skipped — test written after code)
- [ ] 6.8 Run test suite to confirm tests PASS with new code

## 7. Verification and Push

- [ ] 7.1 Run full test suite: `bash tests/check-all.sh`
- [ ] 7.2 Deploy to production and verify with a live PPTX save that participants auto-refresh
- [ ] 7.3 Commit and push to master
