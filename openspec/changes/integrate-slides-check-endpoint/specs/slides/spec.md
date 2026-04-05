## ADDED Requirements

### Requirement: Participant checks slide readiness before downloading PDF
The participant application SHALL call `GET /api/slides/check/{slug}` and wait for a successful response before requesting `GET /api/slides/pdf/{slug}` from Railway. The participant application SHALL NOT issue a PDF download request for that slug before `check` returns HTTP 200.

#### Scenario: Cached PDF path
- **WHEN** participant requests a slide PDF and `GET /api/slides/check/{slug}` returns HTTP 200 immediately
- **THEN** participant SHALL request `GET /api/slides/pdf/{slug}` immediately after the successful check response

#### Scenario: PDF missing or stale
- **WHEN** participant requests a slide PDF and `GET /api/slides/check/{slug}` blocks until backend preparation completes
- **THEN** participant SHALL wait for the check response and only then request `GET /api/slides/pdf/{slug}`

#### Scenario: Check timeout or temporary failure
- **WHEN** `GET /api/slides/check/{slug}` returns non-200 (including HTTP 503)
- **THEN** participant SHALL NOT request `GET /api/slides/pdf/{slug}` for that attempt and SHALL keep the slide in retry/wait state

## MODIFIED Requirements

### Requirement: Daemon gates participant PDF downloads via /check endpoint
The daemon SHALL expose `GET /{sid}/api/slides/check/{slug}` (proxied by Railway). If the PDF is known fresh, daemon SHALL respond 200 immediately. If the PDF is missing or stale, daemon SHALL send a `download_pdf` WS message to Railway, then hold the response open until Railway sends back `pdf_download_complete` for that slug. If Railway does not confirm within 30 seconds, daemon SHALL respond 503. Participant clients SHALL treat this endpoint as the mandatory precondition before any Railway PDF download request.

#### Scenario: PDF is already cached and fresh
- **WHEN** participant calls `GET /{sid}/api/slides/check/{slug}` and daemon knows the PDF is up-to-date
- **THEN** daemon SHALL respond 200 immediately

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
