## MODIFIED Requirements

### Requirement: Participant fetches slides via REST on WS connect
The participant page and host page SHALL call `GET /api/slides` (proxied to daemon) on every WS connect to obtain the initial slides catalog. Cache status SHALL be embedded directly in each slide entry (`slides[].status`) rather than returned as a separate map. Neither page SHALL rely on Railway to push full initial slides state.

#### Scenario: Participant connects while daemon is running
- **WHEN** a participant opens the app after the daemon has started and loaded its catalog
- **THEN** the participant page calls `GET /api/slides` on WS open and receives a non-empty slides list

#### Scenario: Host opens control panel while daemon is running
- **WHEN** the host opens `/host` after the daemon has started and loaded its catalog
- **THEN** the host page calls `GET /api/slides` and renders the footer badge list from the returned `slides[]` entries with embedded `status`

#### Scenario: Host reconnects after Railway restart
- **WHEN** Railway restarts and the host WebSocket reconnects
- **THEN** the host page re-fetches `GET /api/slides` and re-renders the current catalog and embedded cache status

#### Scenario: Participant reconnects after Railway restart
- **WHEN** Railway restarts and the participant WebSocket reconnects
- **THEN** the participant page re-fetches `GET /api/slides` and renders the current slides list
