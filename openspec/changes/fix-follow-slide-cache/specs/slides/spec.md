## MODIFIED Requirements

### Requirement: Participant checks slide readiness before downloading PDF
The participant application SHALL call `GET /api/slides/check/{slug}` and wait for a successful response before requesting `GET /api/slides/download/{slug}` from Railway. The participant application SHALL NOT issue a PDF download request for that slug before `check` returns HTTP 200. During the wait, the participant UI SHALL display an informative loading label: "Preparing slide..." initially, transitioning to "Downloading slide from trainer's library…" after 1.5 seconds if the check has not yet resolved.

#### Scenario: Cached PDF path
- **WHEN** participant requests a slide PDF and `GET /api/slides/check/{slug}` returns HTTP 200 immediately
- **THEN** participant SHALL request `GET /api/slides/download/{slug}` immediately after the successful check response

#### Scenario: PDF missing or stale — download in progress
- **WHEN** participant requests a slide PDF and `GET /api/slides/check/{slug}` blocks while the daemon orchestrates a Railway PDF download
- **THEN** participant SHALL wait for the check response (up to 35 seconds) and only then request `GET /api/slides/download/{slug}`
- **AND** the loading label SHALL update to "Downloading slide from trainer's library…" after 1.5 seconds of waiting

#### Scenario: Check timeout or temporary failure — outside follow mode
- **WHEN** `GET /api/slides/check/{slug}` returns non-200 (including HTTP 503) and the participant is NOT in follow mode
- **THEN** participant SHALL NOT request `GET /api/slides/download/{slug}` for that attempt and SHALL show an error message prompting the user to retry

#### Scenario: Check failure during follow mode — auto-retry on cache event
- **WHEN** `GET /api/slides/check/{slug}` returns non-200 and the participant IS in follow mode (follow is active)
- **THEN** participant SHALL set a pending-follow-retry flag rather than showing a permanent error
- **AND** when a `slides_cache_status` WS event is received, participant SHALL automatically re-queue the follow attempt
