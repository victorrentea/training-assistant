## MODIFIED Requirements

### Requirement: Daemon serves slide index via GET /{sid}/api/slides
The daemon SHALL handle `GET /{sid}/api/slides` (proxied by Railway) and return the merged slide index plus current cache status. Railway SHALL NOT build or own the slide index.

#### Scenario: Participant fetches slide list
- **WHEN** participant calls `GET /{sid}/api/slides`
- **THEN** daemon SHALL respond with `{slides[]}` where each slide entry embeds cache fields (`status`, `size_bytes`, `downloaded_at`) and source metadata (`modified_at`) directly; `modified_at` SHALL be the ISO 8601 UTC timestamp of the PPTX file's last modification time on daemon's disk (`st_mtime`), or `null` if not available (e.g. uploaded slides)

#### Scenario: PPTX file is modified on disk
- **WHEN** daemon detects a PPTX file change via `st_mtime` comparison
- **THEN** daemon SHALL persist the new `st_mtime` as `pptx_mtime` in daemon state for that file so subsequent `/api/slides` responses reflect the updated `modified_at`

---

## MODIFIED Requirements

### Requirement: Daemon broadcasts slides_cache_status as invalidation signal
The daemon SHALL broadcast `{type: "slides_cache_status"}` (no payload) to all connected participants and host whenever slide cache state changes (download complete, status change, or error). Participant and host UIs SHALL treat this message as a trigger to call `GET /{sid}/api/slides` to refresh their local slides state from the authoritative REST endpoint.

#### Scenario: Railway confirms download complete
- **WHEN** Railway sends `pdf_download_complete` to daemon
- **THEN** daemon SHALL update internal cache state and broadcast `{type: "slides_cache_status"}` with no additional fields
- **AND** participant and host UIs that receive this message SHALL call `GET /{sid}/api/slides` to obtain the fresh slides list

#### Scenario: Download times out
- **WHEN** Railway does not send `pdf_download_complete` within 30 seconds of `download_pdf`
- **THEN** daemon SHALL respond 503 to the pending `/check` request and broadcast `{type: "slides_cache_status"}` with no additional fields so participant UIs refresh and clear the "Retry" state

#### Scenario: Participant UI receives slides_cache_status
- **WHEN** participant JS receives a `slides_cache_status` WS message
- **THEN** participant JS SHALL call `GET /{sid}/api/slides` and update its local slides list from the response

#### Scenario: Host UI receives slides_cache_status
- **WHEN** host JS receives a `slides_cache_status` WS message
- **THEN** host JS SHALL call `_refreshHostSlidesCatalog()` (i.e. `GET /{sid}/api/slides`) and re-render the catalog

---

## ADDED Requirements

### Requirement: Participant renders PPTX modified_at timestamp on each topic line
The participant slides dock SHALL display the `modified_at` timestamp on each topic line when available, replacing any previous timestamp display derived from `updated_at`.

#### Scenario: Slide has modified_at set
- **WHEN** a slide entry includes a non-null `modified_at` ISO timestamp
- **THEN** participant slides dock SHALL render a compact human-readable age (e.g. "2h ago", "3 days ago") on that topic's line

#### Scenario: Slide has no modified_at
- **WHEN** a slide entry has `modified_at: null` (uploaded slides or PPTX not yet scanned)
- **THEN** participant slides dock SHALL render no timestamp on that topic's line
