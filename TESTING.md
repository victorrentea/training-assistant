# Testing Rules & Infrastructure

> This file contains all rules and conventions for writing tests in this project.
> Loaded on demand when tests are being written or modified.

---

## Test Directory Structure

```
tests/
├── conftest.py          ← Pytest fixtures (e2e server, browser helpers, cleanup)
├── unit/                ← Unit tests (no server required)
├── integration/         ← Integration tests (local server)
├── e2e/                 ← E2E browser tests (Playwright, local server, no daemon)
├── load/                ← Load tests
└── docker/              ← Hermetic E2E tests (Docker: backend + daemon + browsers)
    ├── Dockerfile.daemon       ← Single-container image
    ├── start_hermetic.sh       ← Orchestrator: backend → mock Drive → daemon → pytest
    ├── build-daemon.sh         ← Build + run convenience script
    ├── mock_drive_server.py    ← Mock Google Drive HTTP server (fixture PDFs)
    ├── generate_fixture_pdfs.py ← Creates numbered-page PDFs for testing
    ├── test_daemon_connected.py ← Daemon WS connection + session start
    ├── test_poll_flow.py       ← Full poll lifecycle
    ├── test_slides_view.py     ← Slide viewing + cache hit verification
    └── test_follow_me.py       ← Follow Me: stub PPT → daemon → participant
```

---

## Testing Principles

### Assert effects, never logs
- **Never assert against log statements.** Logs are for debugging, not verification.
- Assert against **visible effects**: UI state, API responses, file contents, adapter call records.
- Use logs only to orient yourself during debugging.

### Await, don't sleep
- Use Playwright's `expect()` for DOM assertions — it already polls with timeout.
- For non-DOM assertions (API state, files, adapter state), use `_await_condition()`:
  ```python
  def _await_condition(fn, timeout_ms=10000, poll_ms=300, msg=""):
      deadline = time.monotonic() + timeout_ms / 1000
      while time.monotonic() < deadline:
          result = fn()
          if result:
              return result
          time.sleep(poll_ms / 1000)
      raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")
  ```
- Avoid bare `time.sleep()` in tests. If you must wait, use a condition-based wait.

### Test-Drive-Fix bugs
- Start by reproducing the bug manually.
- Write an automated test that fails due to the bug.
- Fix the bug, see the test pass.

### Controllable stubs
- The daemon's macOS adapter (`daemon/adapters/stub.py`) is **controllable via files**:
  - `/tmp/stub-powerpoint.json` — set current presentation + slide number
  - `/tmp/stub-intellij.json` — set current project + branch
  - `/tmp/stub-calls.jsonl` — log of all adapter calls (for observability)
- Tests write to these files to simulate macOS state changes.
- The daemon reads them on each probe cycle (~1s).

### Mock Google Drive
- `mock_drive_server.py` serves fixture PDFs at Drive-like URLs.
- Request counting: `GET /mock-drive/stats` returns `{slug: count}`.
- Reset: `POST /mock-drive/reset-stats`.
- Use this to verify cache hits (0 extra Drive calls) and deduplication.

### Session reuse
- Hermetic tests run sequentially in one container with one backend.
- Use `GET /api/session/active` to detect and reuse existing sessions instead of always creating new ones.
- The host landing page auto-redirects to `/host/{session_id}` if a session is active.

### Page objects
- Reuse `tests/pages/host_page.py` and `tests/pages/participant_page.py` for browser interactions.
- These are shared between local e2e tests and Docker hermetic tests.

---

## Running Tests

### Unit tests (fast, no server)
```bash
pytest tests/unit/ -v
```

### Local e2e tests (Playwright, spins up local server)
```bash
pytest tests/e2e/ -v
pytest tests/e2e/ -v --headed  # watch the browsers
```

### Hermetic Docker tests (full system in one container)
```bash
bash tests/docker/build-daemon.sh
```

### Daemon unit tests
```bash
pytest tests/daemon/ -v
```

---

## Hermetic Test Architecture

```
┌─ Docker Container ──────────────────────────────────────────┐
│                                                              │
│  Mock Google Drive (:9090)                                   │
│    GET /presentation/d/{slug}/export/pdf → fixture PDF       │
│    GET /mock-drive/stats → request counts                    │
│                                                              │
│  FastAPI Backend (:8000)                                     │
│    Real backend with test catalog (3 fixture slides)         │
│                                                              │
│  Real Daemon (DAEMON_ADAPTER=stub, LLM_ADAPTER=stub)         │
│    Reads /tmp/stub-powerpoint.json for PPT state             │
│    Canned Claude responses for quiz/debate/summary           │
│                                                              │
│  Playwright (headless Chromium)                              │
│    Host + Participant browser contexts (isolated)            │
│                                                              │
│  Fixture data:                                               │
│    /tmp/fixture-pdfs/ (generated multi-page PDFs)            │
│    /tmp/test-sessions/ (session folders)                     │
│    /tmp/test-transcriptions/ (transcript files)              │
└──────────────────────────────────────────────────────────────┘
```

---

## Future: Gherkin Layer

Once 5+ test scenarios are stable, add a `pytest-bdd` Gherkin layer:
- `.feature` files with Given/When/Then steps
- Glue code mapping to page objects + stub control API
- Enables non-developer test authoring and intent clarity
