## Context

The daemon currently persists global selection data (`active_session_id`) and some session metadata, while full session state snapshots are not consistently persisted to the canonical per-session storage file. The reported bug is that state changes are not reliably persisted as the session evolves, so daemon restart can restore stale or empty session state.

The requested behavior is explicit disk-backed storage semantics for one file in the session folder:
- read once at daemon startup;
- keep an in-memory source of truth during runtime;
- evaluate state hash and flush `session-state.json` every 3 seconds only if changed;
- explicitly flush once when session is ended;
- avoid runtime re-reads from disk.

## Goals / Non-Goals

**Goals:**
- Define a single canonical session state storage file path: `session-state.json` in the active session folder.
- Guarantee periodic persistence with bounded staleness (max 3 seconds under normal runtime).
- Guarantee explicit final flush on session end.
- Guarantee restore-from-disk on daemon startup before first state sync.
- Keep runtime behavior in-memory (no periodic disk reads).
- Prove durability with a hermetic acceptance test for close/reopen restoring participant name state.

**Non-Goals:**
- Introducing a database engine, background compaction, or journaling.
- Supporting concurrent writers from multiple daemon processes.
- Reading storage file reactively while daemon is already running.

## Decisions

### 1. Use periodic hash-based flush every 3 seconds
Daemon keeps the runtime source of truth in memory. A background flush loop runs every 3 seconds, computes a deterministic hash of the current session snapshot, and writes `session-state.json` atomically only if the hash changed since the previous successful flush.

Alternatives considered:
- Write-through on every mutation: strongest freshness but too much code impact and write churn.
- Time-based flush without hashing: simpler, but writes unchanged snapshots repeatedly.

### 2. Force explicit flush on session end
When host ends a session, daemon triggers an immediate flush of the current in-memory snapshot regardless of interval timing, so the final state is durably stored before teardown.

Alternatives considered:
- Rely only on periodic timer: risks losing the last few seconds if process exits before next tick.
- End-flow custom serialization path: duplicates logic and increases drift risk.

### 3. Load exactly once during daemon bootstrap
At startup, after active session folder resolution and before initial server sync, daemon will read `session-state.json` (if present) into memory. If missing/invalid, daemon starts with empty/default state.

Alternatives considered:
- Re-read file before each operation: higher I/O, race-prone, violates requirement.
- Load lazily on first request: delays consistency and complicates flow.

### 4. Ensure resume self-heals missing/empty storage file
When a session is resumed, daemon will ensure `session-state.json` exists and is non-empty. If the file is missing or empty, daemon will immediately write the current in-memory session snapshot to that file.

Alternatives considered:
- Wait for next mutation to create/populate file: simpler, but leaves resumed sessions without durable snapshot until a later event.
- Fail resume when file is missing/empty: unacceptable UX and conflicts with resilient recovery goals.

### 5. Normalize on `session-state.json` storage contract
The storage contract uses non-hidden `session-state.json` in the session folder as the durable source. Any existing hidden-path usage is migrated to this canonical location for read/write behavior.

Alternatives considered:
- Keep mixed filename usage across flows: superficially backward-compatible, but conflicts with explicit single-file contract and increases drift risk.
- Dual-write to multiple filenames: transition-friendly but increases complexity and divergence risk.

### 6. Add hermetic acceptance test on close/reopen restoration
Add a Docker hermetic Playwright test that executes the real close/reopen flow and asserts participant name persistence:
1) start session and connect participant;
2) set/confirm participant display name in session state;
3) close session and reopen the same session;
4) verify the same participant name is restored in host-visible participant state.

Alternatives considered:
- Unit/integration-only assertions on snapshot files: faster but does not validate end-user recovery behavior.
- Manual QA only: insufficient as regression guard.

## Risks / Trade-offs

- [Periodic flush can lose up to 3 seconds on crash] -> Mitigation: explicit flush on session end plus 3-second interval bound.
- [Legacy sessions may still contain non-canonical state files] -> Mitigation: optional one-time compatibility read during migration, then canonical writes to `session-state.json`.
- [Hashing must be stable/deterministic] -> Mitigation: canonical JSON serialization (sorted keys) before hashing and test coverage for unchanged-state no-op writes.
- [Resume snapshot could overwrite unintended stale data] -> Mitigation: only self-heal when file is missing or empty; otherwise preserve existing file content as startup source.
- [Hermetic test can be slow/flaky] -> Mitigation: isolate scenario, reuse existing hermetic helpers, mark `@pytest.mark.nightly`, and assert with explicit waits.
