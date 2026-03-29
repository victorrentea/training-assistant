# Hermetic Testing Plan — Daemon in Docker

## Goal
Run the full daemon inside Docker alongside the FastAPI backend and Playwright browsers,
with all macOS-specific and external dependencies replaced by adapters/mocks.

## Completed (POC stages)
- [x] Stage 1: Playwright in Docker → production URL
- [x] Stage 2: 3 isolated browser contexts + dummy FastAPI in one container
- [x] Stage 3: Real FastAPI backend + mock daemon (WS only) + host starts session + participant joins

---

## Phase A — Extract macOS adapter (BLOCKER for daemon in Docker)

The daemon cannot run in Linux/Docker because it calls `osascript`, `pkill`, `open -a`,
and reads macOS plist files. All macOS-specific calls must be extracted behind an adapter
interface so we can swap in a no-op/stub implementation for Docker.

### What to extract into `daemon/adapters/macos.py`:

| Current location | Function | What it does |
|---|---|---|
| `daemon/__main__.py` ~L75-123 | PowerPoint probe | osascript → returns (presentation, slide#, frontmost) |
| `daemon/__main__.py` ~L318-340 | PowerPoint slide tracking loop | Periodically probes PowerPoint |
| `daemon/__main__.py` ~L178-250 | Audio Hijack control | pkill + open + plist read/write for language switch |
| `daemon/__main__.py` ~L343-353 | Beep sound | osascript beep |
| `daemon/slides/drive_sync.py` ~L85-95 | Beep on Drive error | osascript beep |
| `daemon/intellij/tracker.py` | IntelliJ probe | osascript + XML parse + git branch |

### Steps:
- [ ] A1. Create `daemon/adapters/macos.py` with a `MacOSAdapter` class (or protocol) exposing:
  - `probe_powerpoint() -> dict | None`
  - `control_audio_hijack(action, language?) -> bool`
  - `probe_intellij() -> dict | None`
  - `beep() -> None`
- [ ] A2. Create `daemon/adapters/stub.py` with `StubAdapter` (all no-ops / fixture returns)
- [ ] A3. Refactor `daemon/__main__.py` to use the adapter (injected via env var or config flag)
- [ ] A4. Refactor `daemon/slides/drive_sync.py` beep call
- [ ] A5. Verify daemon still works on macOS with real adapter
- [ ] A6. Verify daemon starts in Docker with stub adapter (no crashes)

---

## Phase B — Daemon in Docker with fixture data

Run the real daemon process in the same Docker container, with:
- Stub macOS adapter (from Phase A)
- Fixture transcription folder (raw .txt files)
- Fixture session folder (with session_state.json, notes)
- Fixture slides catalog JSON
- Mock Claude API (canned responses)
- Env vars pointing to fixture paths

### Steps:
- [ ] B1. Create fixture data directory structure in `tests/docker/fixtures/`
- [ ] B2. Mock the Anthropic Claude adapter (canned quiz/summary/debate responses)
- [ ] B3. Dockerfile: run backend + daemon + Playwright in one container
- [ ] B4. Test: daemon connects, sends session_sync on reconnect
- [ ] B5. Test: host requests quiz → daemon returns canned quiz → host sees preview

---

## Phase C — Mock Google Drive + slides flow

Add a lightweight HTTP server inside the container that serves fixture PDFs.
The slides catalog points to this mock server instead of real Google Drive.

### Steps:
- [ ] C1. Create fixture PDFs (numbered pages for scroll verification)
- [ ] C2. Create mock Drive HTTP server (HEAD + GET for PDF export URLs)
- [ ] C3. Configure slides catalog to use mock Drive URLs
- [ ] C4. Test: daemon detects PPTX change → signals backend → backend downloads from mock Drive → participant sees slide
- [ ] C5. Test: host "follow me" → participant auto-navigates to correct page

---

## Phase D — Full interaction flows

End-to-end tests with all components:
- [ ] D1. Poll: host creates poll → 2 participants vote → results update live
- [ ] D2. Quiz: host requests quiz → daemon generates (mock Claude) → host opens as poll → participants vote
- [ ] D3. Word cloud: host sets topic → participants submit words → cloud renders
- [ ] D4. Code review: host pastes code → participants select lines → host confirms
- [ ] D5. Debate: full lifecycle including AI cleanup (mock Claude)
- [ ] D6. Leaderboard: top-5 reveal with correct scores
- [ ] D7. Session pause/resume: participants disconnected and reconnected

---

## Integration points reference

| # | Integration | Mock strategy | Phase |
|---|---|---|---|
| 1 | Transcription folder | Fixture .txt files | B |
| 2 | Audio Hijack | Stub adapter (no-op) | A |
| 3 | PPTX watched folder | Fixture files + touch mtime | C |
| 4 | Session folders | Fixture dir with seed JSON/notes | B |
| 5 | Desktop overlay | Lightweight WS mock | B |
| 6 | Anthropic Claude API | Adapter with canned responses | B |
| 7 | Google Drive PDF download (daemon) | **NOT NEEDED** — daemon no longer downloads PDFs (since 590f204). Dead code. | — |
| 7b | Google Drive PDF download (backend) | Mock HTTP server + fixture PDFs | C |
| 8 | PowerPoint probe | Stub adapter (configurable returns) | A |
| 9 | IntelliJ tracker | Stub adapter (no-op) | A |
| 10 | AgentMail notifications | Mock output adapter, verify calls sent | B |
| 11 | OLLAMA transcript cleaner | Mock (uppercase transform for verification) | B |
| 12 | ChromaDB/RAG | Ignore (disabled, never invoked without real LLM) | — |
| 13 | Materials mirror | **Remove entirely** (#93) — obsolete | — |
| 14 | Lock file | Works as-is in Docker | — |
| 15 | Secrets file | Env vars directly | B |
| 16 | Beep sound | Part of macOS adapter stub | A |
| 17 | Slides catalog JSON | Fixture file | C |
