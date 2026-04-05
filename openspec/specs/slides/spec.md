### Requirement: Daemon gates participant PDF downloads via /check endpoint
The daemon SHALL expose `GET /{sid}/api/slides/check/{slug}` (proxied by Railway). If the PDF is known fresh, daemon SHALL respond 200 immediately. If the PDF is missing or stale, daemon SHALL send a `download_pdf` WS message to Railway, then hold the response open until Railway sends back `pdf_download_complete` for that slug. If Railway does not confirm within 30 seconds, daemon SHALL respond 503.

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

---

### Requirement: Daemon serves slide index via GET /{sid}/api/slides
The daemon SHALL handle `GET /{sid}/api/slides` (proxied by Railway) and return the merged slide index plus current cache status. Railway SHALL NOT build or own the slide index.

#### Scenario: Participant fetches slide list
- **WHEN** participant calls `GET /{sid}/api/slides`
- **THEN** daemon SHALL respond with `{slides[], cache_status: {slug→{status, size_bytes}}}` reflecting current daemon state

---

### Requirement: Daemon polls GDrive fingerprints to detect stale PDFs
The daemon SHALL poll GDrive HTTP headers (ETag / Last-Modified / Content-Length) or content SHA256 for each known slug after receiving a `slide_invalidated` signal. When a fingerprint change is detected, daemon SHALL mark that slug stale.

#### Scenario: Fingerprint change detected
- **WHEN** daemon detects the GDrive fingerprint for a slug differs from the stored baseline
- **THEN** daemon SHALL mark that slug as stale so the next `/check` triggers a re-download

#### Scenario: Fingerprint poll timeout
- **WHEN** polling runs for 60 seconds without detecting a change
- **THEN** daemon SHALL stop polling and leave the slug status unchanged

---

### Requirement: Railway downloads PDFs only on daemon instruction
Railway SHALL execute a GDrive HTTP pull for a slug only when it receives a `download_pdf` WS message from the daemon. Railway SHALL NOT autonomously trigger downloads. After completing (or failing) the download, Railway SHALL send `{type: "pdf_download_complete", slug, status: "ok"|"error"}` to daemon via WS.

#### Scenario: Railway receives download_pdf instruction
- **WHEN** Railway receives `{type: "download_pdf", slug, drive_export_url}` from daemon
- **THEN** Railway SHALL download the PDF from `drive_export_url`, write it to `/tmp/slides-cache/{slug}.pdf`, and send `pdf_download_complete` with `status: "ok"` to daemon

#### Scenario: Railway download fails
- **WHEN** Railway fails to download or the content is not a valid PDF
- **THEN** Railway SHALL send `pdf_download_complete` with `status: "error"` to daemon

#### Scenario: Duplicate download_pdf for in-flight slug
- **WHEN** Railway receives `download_pdf` for a slug that is already downloading
- **THEN** Railway SHALL not start a second download; it SHALL send `pdf_download_complete` once the in-flight download finishes

---

### Requirement: Daemon issues downloads only on participant /check — no proactive pre-warming
The daemon SHALL NOT issue `download_pdf` instructions proactively on reconnect, catalog push, or any background schedule. Downloads are triggered exclusively by participant `/check` requests. This avoids unnecessary GDrive→Railway traffic for slides no participant is actively viewing.

#### Scenario: Daemon receives slides_catalog — no downloads issued
- **WHEN** daemon receives a `slides_catalog` WS message from Railway with new slug entries
- **THEN** daemon SHALL update its internal catalog state and SHALL NOT send any `download_pdf` messages

#### Scenario: Daemon reconnects to Railway — no downloads issued
- **WHEN** daemon reconnects to Railway via WS
- **THEN** daemon SHALL NOT proactively issue `download_pdf` for any slugs; downloads only happen when participants request them via `/check`

---

### Requirement: Participant fetches slides via REST on WS connect
The participant page SHALL call `GET /api/slides` (proxied to daemon) on every WS connect to obtain the initial slides catalog and cache status. It SHALL NOT rely on Railway to push slides state.

#### Scenario: Participant connects while daemon is running
- **WHEN** a participant opens the app after the daemon has started and loaded its catalog
- **THEN** the participant page calls `GET /api/slides` on WS open and receives a non-empty slides list

#### Scenario: Participant reconnects after Railway restart
- **WHEN** Railway restarts and the participant WebSocket reconnects
- **THEN** the participant page re-fetches `GET /api/slides` and renders the current slides list

---

### Requirement: Daemon initializes slides state from catalog file on startup
The daemon SHALL populate `misc_state.slides_catalog` and `misc_state.slides_cache_status` during `SlidesPollingRunner.start()`, so `GET /api/slides` returns correct data immediately after the daemon starts.

#### Scenario: Daemon starts with a configured catalog file
- **WHEN** the daemon starts with a valid `PPTX_CATALOG_FILE`
- **THEN** `misc_state.slides_catalog` is non-empty with entries containing `slug`, `title`, `drive_export_url`
- **THEN** `misc_state.slides_cache_status` reflects whether each PDF exists on disk

---

### Requirement: Daemon broadcasts slides_cache_status on PDF cache changes
The daemon SHALL broadcast a `slides_cache_status` WS message to all participants whenever a PDF is downloaded or its cache state changes. Railway SHALL fan it out to connected participants unchanged.

#### Scenario: PDF download completes
- **WHEN** a PDF download completes (success or error)
- **THEN** all connected participants receive a `slides_cache_status` WS message with the updated status for the affected slug

---

### Requirement: Railway does not push slides state to participants on connect
Railway SHALL NOT send `slides_cache_status` in the initial WS messages to participants.

#### Scenario: Participant WS connect
- **WHEN** a participant WebSocket connects
- **THEN** Railway does NOT send a `slides_cache_status` message as part of the initial state push

---

### Requirement: Current slide tracked via WS push from addons bridge
The daemon SHALL update `slides_current` state when it receives a `slide_changed` message from the addon-bridge, replacing the previous `activity-slides-*.md` file-polling loop. The daemon SHALL broadcast `slides_current` to all connected participants and the host immediately upon receiving the event.

#### Scenario: Slide navigation received over WS
- **WHEN** daemon receives `{"type": "slide_changed", "deck": "AI Coding.pptx", "slide": 15}` from the bridge
- **THEN** daemon updates `misc_state.slides_current` to `{deck: "AI Coding.pptx", slide: 15}` and broadcasts `slides_current` to all participants and host within 100 ms

#### Scenario: PowerPoint closed — slides_current cleared
- **WHEN** daemon receives `{"type": "slide_changed", "deck": null, "slide": null}`
- **THEN** daemon sets `misc_state.slides_current = null` and broadcasts the update

#### Scenario: Bridge not connected — slides_current unchanged
- **WHEN** the addon-bridge WS client is disconnected
- **THEN** daemon retains the last known `slides_current` value (no reset, no file-poll fallback)
