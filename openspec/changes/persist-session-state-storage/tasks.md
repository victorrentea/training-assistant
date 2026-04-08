## 1. Canonical storage path and I/O primitives

- [x] 1.1 Introduce a single constant/helper for session state storage path (`session-state.json`) in daemon session-state utilities
- [x] 1.2 Ensure session-state write helper performs atomic JSON writes (tmp + replace) with UTF-8 encoding and structured error logging
- [x] 1.3 Add startup load helper for `session-state.json` that returns default/empty state on missing file and logs parse failures without crashing daemon

## 2. Startup restore flow

- [x] 2.1 Update daemon bootstrap flow to load session state once from active session folder before initial backend sync
- [x] 2.2 Wire restored snapshot into existing startup sync path so host receives restored state immediately after daemon starts
- [x] 2.3 Preserve current behavior when there is no active session (skip session-state load)

## 3. Periodic hash-based persistence

- [x] 3.1 Implement a 3-second flush loop that computes a deterministic hash of in-memory session state
- [x] 3.2 Write `session-state.json` only when the current hash differs from the last flushed hash
- [x] 3.3 Trigger an explicit immediate flush on session end (independent of periodic timer)
- [x] 3.4 On resume, if `session-state.json` is missing or empty, create/populate it immediately from current in-memory session snapshot
- [x] 3.5 Remove runtime disk re-read usage from reconnect/loop paths so runtime source of truth remains in memory

## 4. Verification

- [x] 4.1 Add/adjust daemon tests for startup restore from `session-state.json` (existing file, missing file, invalid JSON)
- [x] 4.2 Add/adjust daemon tests for periodic flush behavior (changed hash writes; unchanged hash skips writes)
- [x] 4.3 Add/adjust daemon tests for explicit end-session flush and resume self-healing (missing file, empty file)
- [x] 4.4 Add hermetic E2E acceptance test (e.g. `tests/docker/test_session_state_participant_name_restore.py`) that validates participant name survives session close + reopen
- [x] 4.5 Mark the new hermetic test with `@pytest.mark.nightly` and use existing Docker session helpers for deterministic setup
- [x] 4.6 Run `bash tests/run-daemon-tests.sh` and `bash tests/docker/run-hermetic.sh` and capture evidence that persistence behavior passes
