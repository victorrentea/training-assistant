## 1. Railway: New WS messages

- [x] 1.1 Add `download_pdf` WS message handler on Railway: receives `{slug, drive_export_url}`, triggers existing `_do_download` machinery, deduplicates in-flight downloads for same slug
- [x] 1.2 After download completes (success or failure), send `{type: "pdf_download_complete", slug, status: "ok"|"error"}` to daemon via the daemon WS connection

## 2. Railway: Remove autonomous download triggering

- [x] 2.1 Remove autonomous `handle_slide_invalidated` call from Railway's WS handler — Railway no longer self-triggers downloads on `slide_invalidated`
- [x] 2.2 Remove `seed_catalog_from_file()` call from Railway startup (`app.py` lifespan)
- [x] 2.3 Update Railway `GET /{sid}/api/slides` to proxy to daemon (consistent with other participant endpoints) — remove local index building
- [x] 2.4 Remove `_build_catalog_slides_index`, `_build_local_slides_index`, `_build_uploaded_slides_index`, `_merge_slide_sources`, `_collect_participant_slides` from `router.py`
- [ ] 2.5 Remove dead AppState fields: `slides_gdrive_locks`, `slides_download_events`, `slides_fingerprints`, `slides_download_semaphore` from `shared/state.py` (deferred — still used by cache.py)

## 3. Daemon: /check endpoint

- [x] 3.1 Add `GET /{sid}/api/slides/check/{slug}` on daemon — returns 200 immediately if slug is known fresh
- [x] 3.2 If slug is missing or stale: send `download_pdf` WS to Railway, register a pending future for that slug, hold HTTP response open
- [x] 3.3 Coalesce concurrent `/check` calls for same slug — only one `download_pdf` sent; all waiters resolved together
- [x] 3.4 Implement 30s timeout: if `pdf_download_complete` not received, respond 503 and clean up the pending future
- [x] 3.5 Handle `pdf_download_complete` WS message from Railway — resolve all pending `/check` futures for that slug with 200 (ok) or 503 (error)

## 4. Daemon: GET /{sid}/api/slides

- [x] 4.1 Add `GET /{sid}/api/slides` on daemon — returns `{slides[], cache_status: {slug→{status, size_bytes}}}` from daemon state
- [x] 4.2 Ensure Railway proxies `GET /{sid}/api/slides` to daemon (remove or replace local handler)

## 5. Daemon: Fingerprint polling

- [x] 5.1 Port `_probe_fingerprint_sync` + async wrapper from `railway/features/slides/cache.py` into `daemon/slides/convert.py`
- [x] 5.2 Port `_poll_fingerprint_loop` into `daemon/slides/convert.py` — on fingerprint change, mark slug stale in daemon cache-status dict
- [x] 5.3 Connect existing `slide_invalidated` handler in `daemon/slides/loop.py` to start fingerprint polling via updated `convert.py`

## 6. Daemon: Broadcast on download complete

- [x] 6.1 On `pdf_download_complete` received from Railway: update daemon's cache-status dict for that slug
- [x] 6.2 Broadcast `slides_cache_status` to all connected participants (clears "Retry"/error state in participant UI, shows green cached indicator)

## 7. Cleanup & Tests

- [x] 7.1 Remove unused imports from `railway/features/slides/router.py` and `railway/features/ws/router.py` after removing autonomous download logic
- [x] 7.2 Add unit tests for daemon `/check`: immediate 200 when fresh, blocks then 200 on `pdf_download_complete`, 503 on timeout, coalescing of concurrent calls
- [x] 7.3 Add unit tests for Railway `download_pdf` handler: deduplication of in-flight downloads, sends `pdf_download_complete` on success and failure
- [ ] 7.4 Hermetic E2E test: participant calls /check/{slug} → daemon sends download_pdf to Railway → Railway fetches from mock GDrive → pdf_download_complete to daemon → /check returns 200 → participant downloads PDF binary
