## Why

Daemon restarts currently lose in-memory session state, which breaks continuity for active workshops and requires manual recovery. Persisting state to disk ensures sessions resume predictably after daemon restarts or crashes.

## What Changes

- Persist daemon session state to `session-state.json` inside the active session folder via periodic flushes every 3 seconds.
- Load session state from that file once at daemon startup and use it as the in-memory source of truth for runtime operations.
- Use state hashing between flush intervals; write to disk only when the session-state hash changed since the previous flush.
- On session end, perform an explicit immediate flush to disk.
- Define behavior for first run and missing file scenarios (initialize empty/default state).
- On session resume, if `session-state.json` is missing or empty, create/populate it from the current in-memory session snapshot.
- Add a hermetic end-to-end acceptance test proving that after session close + reopen, a participant name stored in session state is restored.

## Capabilities

### New Capabilities
- `daemon-session-state-storage`: Disk-backed persistence contract for daemon session state lifecycle (startup load + hash-based periodic flush + explicit flush on session end).

### Modified Capabilities
- None.

## Impact

- Affected code: daemon session state model, mutation paths, daemon startup bootstrap, session folder file I/O.
- Files/API surface: session folder `session-state.json` becomes required runtime storage artifact.
- Tests: new hermetic E2E coverage for session close/reopen state restoration (participant name persistence).
- Operational impact: improved restart resilience with controlled write frequency (single read at startup, hash-checked flush every 3s, forced flush on end).
