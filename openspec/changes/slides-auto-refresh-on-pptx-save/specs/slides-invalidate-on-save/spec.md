## ADDED Requirements

### Requirement: Slides upload daemon triggers Railway cache invalidation after successful GDrive download
After `process_one_file()` successfully downloads a fresh PDF from Google Drive, the slides upload daemon SHALL call `POST /api/slides/invalidate/{slug}` on the main daemon (at `DAEMON_LOCAL_URL`, defaulting to `http://localhost:8081`) with host authentication. Failure to reach the main daemon SHALL be logged as a warning and SHALL NOT cause the slides upload daemon to fail or retry.

#### Scenario: PPTX saved and new PDF downloaded from GDrive
- **WHEN** the slides upload daemon completes `process_one_file()` for a slug
- **THEN** it SHALL call `POST /api/slides/invalidate/{slug}` on the main daemon within the same poll cycle
- **AND** if the call fails (daemon unreachable, HTTP error), it SHALL log a warning and continue

---

### Requirement: Main daemon exposes POST /api/slides/invalidate/{slug} (host-auth only)
The main daemon SHALL expose `POST /api/slides/invalidate/{slug}` requiring HTTP Basic Auth. On receiving this request, it SHALL mark `misc_state.slides_cache_status[slug]["status"] = "stale"` and send a `{type: "download_pdf", slug, drive_export_url}` WS message to Railway. The `drive_export_url` SHALL be taken from `misc_state.slides_catalog[slug]["drive_export_url"]` if available, or omitted if not.

#### Scenario: Invalidate called while slug is cached on Railway
- **WHEN** `POST /api/slides/invalidate/{slug}` is called and slug status is `cached`
- **THEN** daemon updates status to `stale`, sends `download_pdf` to Railway, and returns HTTP 200

#### Scenario: Invalidate called while daemon WS to Railway is disconnected
- **WHEN** `POST /api/slides/invalidate/{slug}` is called and the Railway WS is not connected
- **THEN** daemon marks status as `stale`, logs a warning, and returns HTTP 503

#### Scenario: Invalidate called for unknown slug
- **WHEN** `POST /api/slides/invalidate/{slug}` is called for a slug not in the catalog
- **THEN** daemon returns HTTP 404

---

### Requirement: Railway re-downloads the PDF and notifies daemon on completion
Upon receiving `{type: "download_pdf", slug, drive_export_url}` from the daemon, Railway SHALL download the PDF from `drive_export_url` (replacing any existing cached file), update its `slides_cache_status`, send `pdf_download_complete` back to the daemon, and broadcast `slides_cache_status` to all connected participants and host.

#### Scenario: Railway receives download_pdf for a previously cached slug
- **WHEN** Railway receives `download_pdf` for slug `S` and `/tmp/slides-cache/S.pdf` already exists
- **THEN** Railway SHALL overwrite the cached file with the fresh download
- **AND** broadcast `slides_cache_status` to all participants after completing

#### Scenario: Railway download fails
- **WHEN** Railway fails to download the PDF (network error, non-PDF response)
- **THEN** Railway SHALL send `pdf_download_complete` with `status: "error"` and broadcast `slides_cache_status` with status `download_failed`
