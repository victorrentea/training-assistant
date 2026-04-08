## ADDED Requirements

### Requirement: Daemon persists session state via periodic hash-checked flush
The daemon SHALL run a periodic flush loop every 3 seconds. On each tick, daemon SHALL compute a deterministic hash of the current in-memory session state snapshot and atomically write `session-state.json` only if the hash differs from the last successfully flushed hash.

#### Scenario: State changed since previous flush
- **WHEN** the 3-second flush tick executes and the current session-state hash differs from the previously flushed hash
- **THEN** daemon SHALL atomically write the full current snapshot to `session-state.json` in the active session folder

#### Scenario: State unchanged since previous flush
- **WHEN** the 3-second flush tick executes and the current session-state hash is identical to the previously flushed hash
- **THEN** daemon SHALL skip disk write for that tick

#### Scenario: No active session folder
- **WHEN** a periodic flush tick executes while no active session is resolved
- **THEN** daemon SHALL keep in-memory state consistent and SHALL NOT attempt to write `session-state.json`

### Requirement: Daemon flushes immediately when session ends
When the current session is ended, daemon SHALL perform an explicit immediate flush of the current in-memory session state snapshot to `session-state.json` before teardown/transition completes.

#### Scenario: End session triggers final backup flush
- **WHEN** host triggers session end for an active session
- **THEN** daemon SHALL write the current in-memory session snapshot to `session-state.json` immediately, independent of periodic flush timing

### Requirement: Daemon restores state from disk at startup only
The daemon SHALL read `session-state.json` from the resolved active session folder during startup bootstrap and use that snapshot to initialize in-memory session state before first sync to backend.

#### Scenario: Storage file exists at startup
- **WHEN** daemon starts and active session folder contains `session-state.json`
- **THEN** daemon SHALL load that JSON into in-memory session state before sending startup state sync

#### Scenario: Storage file missing at startup
- **WHEN** daemon starts and active session folder does not contain `session-state.json`
- **THEN** daemon SHALL initialize in-memory state with defaults and continue running without startup failure

### Requirement: Resume flow self-heals missing or empty storage file
When resuming a session, the daemon SHALL ensure `session-state.json` exists and contains a JSON snapshot. If the file is missing or empty, the daemon SHALL write the current in-memory session snapshot to initialize storage.

#### Scenario: Resume with missing storage file
- **WHEN** daemon resumes a session and `session-state.json` does not exist in that session folder
- **THEN** daemon SHALL create `session-state.json` and write the current in-memory session snapshot

#### Scenario: Resume with empty storage file
- **WHEN** daemon resumes a session and `session-state.json` exists but is empty
- **THEN** daemon SHALL overwrite it with the current in-memory session snapshot

### Requirement: Runtime source of truth remains in memory
After startup initialization, the daemon SHALL treat in-memory session state as the runtime source of truth and SHALL NOT re-read `session-state.json` during normal execution.

#### Scenario: Runtime operations after startup
- **WHEN** daemon handles runtime requests and events after startup bootstrap is complete
- **THEN** daemon SHALL use in-memory session state and SHALL update disk storage only via periodic hash-checked flush and explicit end-session flush

### Requirement: Participant name state survives session close and reopen
Session state persistence SHALL preserve participant naming data across session close/reopen flows so host-visible participant names are restored when the same session is resumed.

#### Scenario: Participant name restored after reopen
- **WHEN** a participant name is present in session state, the session is closed, and the same session is reopened
- **THEN** daemon SHALL restore participant naming data from `session-state.json`
- **AND** host-visible participant state SHALL show the same participant name after reopen
