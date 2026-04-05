## MODIFIED Requirements

### Requirement: Daemon gates participant PDF downloads via /check endpoint
The daemon SHALL expose `GET /{sid}/api/slides/check/{slug}` (proxied by Railway). If the PDF is known fresh on Railway and immediately downloadable from `/{sid}/api/slides/download/{slug}`, daemon SHALL respond 200 immediately. If Railway availability is not confirmed for that slug, daemon SHALL send a `download_pdf` WS message to Railway, then hold the response open until Railway sends back `pdf_download_complete` for that slug. If Railway does not confirm within 30 seconds, daemon SHALL respond 503.

#### Scenario: PDF is already cached and Railway-served
- **WHEN** participant calls `GET /{sid}/api/slides/check/{slug}` and daemon confirms the same slug is currently downloadable from Railway
- **THEN** daemon SHALL respond 200 immediately

#### Scenario: Daemon-local cached state without Railway file
- **WHEN** participant calls `GET /{sid}/api/slides/check/{slug}` and daemon has local `cached` status but Railway cannot currently serve `/{sid}/api/slides/download/{slug}`
- **THEN** daemon SHALL treat the slug as not ready, send `{type: "download_pdf", slug, drive_export_url}` to Railway, and respond 200 only after `pdf_download_complete` with `status: "ok"`

#### Scenario: PDF is missing — Railway downloads on daemon instruction
- **WHEN** participant calls `GET /{sid}/api/slides/check/{slug}` and the PDF is not yet on Railway disk
- **THEN** daemon SHALL send `{type: "download_pdf", slug, drive_export_url}` to Railway via WS, hold the response open, and respond 200 once Railway sends `pdf_download_complete`

#### Scenario: PDF is stale — daemon triggers refresh
- **WHEN** daemon has detected via fingerprint polling that a newer PDF is available on GDrive
- **THEN** daemon SHALL mark the slug stale, and the next `/check` for that slug SHALL trigger a re-download before responding 200

#### Scenario: Download timeout — 503 to participant, download continues
- **WHEN** Railway does not send `pdf_download_complete` within 30 seconds of `download_pdf`
- **THEN** daemon SHALL respond 503 to the pending `/check` request; Railway SHALL continue downloading; when Railway eventually sends `pdf_download_complete`, daemon SHALL broadcast `slides_cache_status` to all participants so their UI clears the "Retry" state and shows the green cached indicator

#### Scenario: Concurrent /check calls for same slug
- **WHEN** multiple participants call `/check` for the same slug while a download is in progress
- **THEN** daemon SHALL coalesce them — only one `download_pdf` WS message sent; all pending `/check` requests resolve together when `pdf_download_complete` arrives

## ADDED Requirements

### Requirement: Participant download actions SHALL use the same readiness gate as slide viewing
The participant UI SHALL call `GET /{sid}/api/slides/check/{slug}` before triggering any user-initiated slide file download from the slide list. If readiness returns non-200, the UI SHALL avoid navigating to the download URL and SHALL show a retryable error state.

#### Scenario: Download click when slide is ready
- **WHEN** participant clicks the download icon for a slide and `/check` returns 200
- **THEN** the UI SHALL continue with the slide download request to `/{sid}/api/slides/download/{slug}`

#### Scenario: Download click while slide is still preparing
- **WHEN** participant clicks the download icon and `/check` returns non-200
- **THEN** the UI SHALL not navigate to the download URL and SHALL display a message that the slide is still preparing
