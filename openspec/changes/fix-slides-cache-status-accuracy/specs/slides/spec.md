## MODIFIED Requirements

### Requirement: Daemon gates participant PDF downloads via /check endpoint
The daemon SHALL expose `GET /{sid}/api/slides/check/{slug}` (proxied by Railway). If the PDF is known fresh and is actually present on Railway disk, daemon SHALL respond 200 immediately. If daemon cache state says `cached` but Railway probe indicates missing file, daemon SHALL downgrade that slug to `not_cached` and trigger normal download flow. If the PDF is missing or stale, daemon SHALL send a `download_pdf` WS message to Railway, then hold the response open until Railway sends back `pdf_download_complete` for that slug. If Railway does not confirm within 30 seconds, daemon SHALL respond 503.

#### Scenario: PDF is already cached and fresh on Railway
- **WHEN** participant calls `GET /{sid}/api/slides/check/{slug}` and daemon status is `cached` and Railway confirms availability
- **THEN** daemon SHALL respond 200 immediately

#### Scenario: Daemon says cached but Railway file is missing
- **WHEN** participant calls `GET /{sid}/api/slides/check/{slug}` and daemon status is `cached` but Railway probe fails with missing file
- **THEN** daemon SHALL set slug status to `not_cached`, send `download_pdf`, and respond only after `pdf_download_complete`

#### Scenario: PDF is missing — Railway downloads on daemon instruction
- **WHEN** participant calls `GET /{sid}/api/slides/check/{slug}` and the PDF is not yet on Railway disk
- **THEN** daemon SHALL send `{type: "download_pdf", slug, drive_export_url}` to Railway via WS, hold the response open, and respond 200 once Railway sends `pdf_download_complete`

#### Scenario: PDF is stale — daemon triggers refresh
- **WHEN** daemon has detected via fingerprint polling that a newer PDF is available on GDrive
- **THEN** daemon SHALL mark the slug stale, and the next `/check` for that slug SHALL trigger a re-download before responding 200

#### Scenario: Download timeout — 503 to participant, download continues
- **WHEN** Railway does not send `pdf_download_complete` within 30 seconds of `download_pdf`
- **THEN** daemon SHALL respond 503 to the pending `/check` request; Railway SHALL continue downloading; when Railway eventually sends `pdf_download_complete`, daemon SHALL broadcast `slides_cache_status` so clients clear retry/loading state and show cached

#### Scenario: Concurrent /check calls for same slug
- **WHEN** multiple participants call `/check` for the same slug while a download is in progress
- **THEN** daemon SHALL coalesce them — only one `download_pdf` WS message sent; all pending `/check` requests resolve together when `pdf_download_complete` arrives

### Requirement: Daemon initializes slides state from catalog file on startup
The daemon SHALL populate `misc_state.slides_catalog` and `misc_state.slides_cache_status` during `SlidesPollingRunner.start()`, so `GET /api/slides` returns correct data immediately after daemon starts. Initial cache status SHALL represent Railway PDF availability, not local daemon-side publish artifacts.

#### Scenario: Daemon starts with a configured catalog file
- **WHEN** the daemon starts with a valid `PPTX_CATALOG_FILE`
- **THEN** `misc_state.slides_catalog` is non-empty with entries containing `slug`, `title`, `drive_export_url`
- **THEN** `misc_state.slides_cache_status` initializes each slug to `cached` only if Railway availability is confirmed, otherwise `not_cached`

### Requirement: Daemon broadcasts slides_cache_status on PDF cache changes
The daemon SHALL broadcast a `slides_cache_status` WS message to participants and host whenever a PDF cache state changes (`not_cached`, `downloading`, `cached`, `stale`, `download_failed`, timeout states). Railway SHALL fan it out unchanged.

#### Scenario: Download starts
- **WHEN** daemon instructs Railway to download a slug
- **THEN** clients receive `slides_cache_status` with that slug marked `downloading`

#### Scenario: PDF download completes successfully
- **WHEN** daemon receives `pdf_download_complete` with `status: "ok"`
- **THEN** daemon updates slug status to `cached` and broadcasts `slides_cache_status` so loading indicators transition to green/cached

#### Scenario: PDF download fails
- **WHEN** daemon receives `pdf_download_complete` with `status: "error"`
- **THEN** daemon updates slug status to `download_failed` and broadcasts the update
