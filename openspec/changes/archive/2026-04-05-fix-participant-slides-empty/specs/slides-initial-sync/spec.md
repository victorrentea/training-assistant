## ADDED Requirements

### Requirement: Participant fetches slides via REST on WS connect
The participant page SHALL call `GET /api/slides` (proxied to daemon) on every WS connect to obtain the initial slides catalog and cache status. It SHALL NOT rely on Railway to push slides state.

#### Scenario: Participant connects while daemon is running
- **WHEN** a participant opens the app after the daemon has started and loaded its catalog
- **THEN** the participant page calls `GET /api/slides` on WS open and receives a non-empty slides list

#### Scenario: Participant reconnects after Railway restart
- **WHEN** Railway restarts and the participant WebSocket reconnects
- **THEN** the participant page re-fetches `GET /api/slides` and renders the current slides list

### Requirement: Daemon initializes slides state from catalog file on startup
The daemon SHALL populate `misc_state.slides_catalog` and `misc_state.slides_cache_status` during `SlidesPollingRunner.start()`, so `GET /api/slides` returns correct data immediately after the daemon starts.

#### Scenario: Daemon starts with a configured catalog file
- **WHEN** the daemon starts with a valid `PPTX_CATALOG_FILE`
- **THEN** `misc_state.slides_catalog` is non-empty with entries containing `slug`, `title`, `drive_export_url`
- **THEN** `misc_state.slides_cache_status` reflects whether each PDF exists on disk

### Requirement: Daemon broadcasts slides_cache_status on PDF cache changes
The daemon SHALL broadcast a `slides_cache_status` WS message to all participants whenever a PDF is downloaded or its cache state changes. Railway SHALL fan it out to connected participants unchanged.

#### Scenario: PDF download completes
- **WHEN** a PDF download completes (success or error)
- **THEN** all connected participants receive a `slides_cache_status` WS message with the updated status for the affected slug

### Requirement: Railway does not push slides state to participants on connect
Railway SHALL NOT send `slides_cache_status` in the initial WS messages to participants.

#### Scenario: Participant WS connect
- **WHEN** a participant WebSocket connects
- **THEN** Railway does NOT send a `slides_cache_status` message as part of the initial state push
