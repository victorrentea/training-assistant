# Workshop Live Interaction Tool — Project Context

This document captures all requirements, decisions, and context for the project.
It is intended as the primary reference for any AI coding assistant working on this codebase.

**Core product goal:** Maximize audience engagement during live workshops and webinars. The target audience is tired, bored, and distracted. Every feature should serve this goal — competition, real-time feedback, and interactivity are not nice-to-haves, they are the point.

---

## Secrets

Host panel credentials are stored in `~/.training-assistants-secrets.env` (never commit secrets).
The file contains `HOST_USERNAME` and `HOST_PASSWORD` for accessing `/host` and `/api/poll`, `/api/poll/status`, `/api/qa/question/{id}` (PATCH, DELETE), `/api/qa/answer/{id}`, `/api/qa/clear`, `/api/activity`, `/api/wordcloud/clear`, `/api/codereview`, `/api/codereview/status`, `/api/codereview/confirm-line`, `/api/mode`, `/api/leaderboard/show`, `/api/leaderboard/hide`.

---

## Production Deployment

- **URL**: https://interact.victorrentea.ro
- **Platform**: [Railway](https://railway.app) — auto-deploys on every push to `master`
- **Deploy**: `git push` to `master` → Railway builds and deploys in ~40-50 seconds. No manual steps.
- **Auth**: HTTP Basic Auth on `/host`, `/api/poll`, `/api/poll/status`, `/api/qa/question/{id}` (PATCH, DELETE), `/api/qa/answer/{id}`, `/api/qa/clear`, `/api/activity`, `/api/wordcloud/clear`, `/api/codereview`, `/api/codereview/status`, `/api/codereview/confirm-line`, `/api/mode`, `/api/leaderboard/show`, `/api/leaderboard/hide` — participants access `/`, `/api/suggest-name`, `/api/status` freely; Q&A submit and upvote go through WebSocket (no REST endpoints)
- **Versioning**: `static/version.js` is generated at Railway deploy time (not committed to git); a GitHub Action generates `static/deploy-info.json` with changelog on each push to master; both host and participant pages display the version age in the bottom-right corner

---

## Project Goal

Build a **self-hosted, real-time audience interaction tool** for use during online webinars and workshops. The host (facilitator) controls the session from a dedicated panel; participants join via a shared browser link with no installation required. The tool must work reliably with groups of 30–150 concurrent participants.

---

## Functional Requirements

### Participant experience
- Join a session by opening a URL in any browser — **no app install, no account, no login**
- Set a display name on first visit; the name is **persisted in `localStorage`** and pre-filled on return visits from the same browser
- On joining, browser requests geolocation permission; if granted, city+country is sent to server via WebSocket `location` message; if denied, the IANA timezone is sent instead
- Interact with live activities (polls, future: Q&A, word cloud) in real time
- See results update live without any page reload

### Host experience
- Single host control panel at `/host` (protected by HTTP Basic Auth)
- Create, open, close, and remove polls
- See live vote counts and results as participants vote
- See connected participant count and location/timezone per participant in real time

### Session model
- **Single active room** at any time — no multi-room, no session codes
- State is **in-memory** (Python dict); no database required
- State resets on server restart — this is acceptable (sessions are short, live events)

---

## Interaction Features

### Phase 1 — implemented
- **Live Poll**: host creates a question with 2–8 options; participants vote once; results shown as animated bar charts updating in real time for everyone

### Phase 2 — implemented
- **Q&A with upvoting**: participants submit questions via WebSocket; others can upvote; host sees ranked list; gamified with points
- **Word cloud**: participants submit words; host displays an animated word cloud with topic prompt
- **Code Review**: host pastes a code snippet, participants flag problematic lines, host confirms correct lines one by one — awarding points and sparking discussion
- **Leaderboard**: Kahoot-style top-5 dramatic reveal triggered by host; sequential position reveal from 5th to 1st; participants see personal rank on their phone; works in both workshop and conference modes
- **Conference mode identity**: auto-assigned character names from movies/games (251 pool); 2-letter avatars with deterministic colors; optional rename via edit icon (not prompted)

### Phase 3 — future AI integration
- Claude API integration for Q&A summarisation, automated responses, or word cloud insights

---

## Non-Functional Requirements

- **Always-on**: zero cold starts or sleep behaviour — participants must never wait for the server to wake up
- **Free hosting**: must run on a permanently free tier with no time expiry
- **No frontend build step**: plain HTML + vanilla JavaScript only — no npm, no bundler, no framework compilation
- **No participant install**: everything works in a standard browser tab
- **Language**: participant UI in **English**; host UI in English
- **No large data through host machine**: the daemon (running on the host's Mac) must never download or proxy large files (PDFs, media) from external services. All large-file downloads (e.g. slide PDFs from Google Drive) must happen on the backend (Railway), not on the host's machine. The daemon may signal the backend to fetch content, but must not fetch and re-upload it.

---

## Technology Stack

### Backend
| Concern | Choice | Notes |
|---|---|---|
| Language | **Python 3.12** | Local dev and Railway both use Python 3.12 |
| Framework | **FastAPI** | Async, WebSocket support native, auto Swagger UI at `/docs` |
| Real-time transport | **WebSockets** (native FastAPI) | One persistent WS connection per participant; server broadcasts state changes |
| State storage | **In-memory Python dict** | Sufficient for single-room, short-duration live sessions |
| ASGI server | **Uvicorn** | `python3 -m uvicorn railway.app:app --host 127.0.0.1 --port 8000` |

### Frontend
| Concern | Choice | Notes |
|---|---|---|
| Language | **Vanilla JavaScript (ES6+)** | No framework, no build step |
| Markup | **Plain HTML5** | Single-file pages per role |
| Styling | **Inline CSS** (per file) | Dark theme, CSS variables, no external CSS framework |
| Participant identity | **UUID (`crypto.randomUUID()`)** | `sessionStorage` if host cookie present (per-tab), else `localStorage` (per-browser). Key: `workshop_participant_uuid` |
| Participant name persistence | **`localStorage`** | Key: `workshop_participant_name` (pre-fill convenience) |
| WebSocket client | **Native browser WebSocket API** | Auto-reconnect on disconnect (3s retry) |
| Geolocation | **Browser Geolocation API** + Nominatim reverse geocoding | Falls back to `Intl.DateTimeFormat` timezone if denied |

### Infrastructure
| Concern | Choice | Notes |
|---|---|---|
| Hosting | **Railway** | Auto-deploys on `git push` to master, ~40-50s build time |
| HTTPS | **Railway** | Handles TLS automatically |
| Auth | **HTTP Basic Auth** (FastAPI middleware) | Protects `/host`, `/api/poll`, `/api/poll/status`, host-only Q&A and activity endpoints |

---

## Project Structure

```
training-assistant/
├── railway/                 ← Railway backend (FastAPI app deployed to Railway)
│   ├── app.py               ← FastAPI application (entry point, mounts all feature routers)
│   ├── healthcheck.py       ← Health check endpoint
│   ├── shared/              ← Shared infrastructure
│   │   ├── state.py         ← AppState singleton (all dicts UUID-keyed)
│   │   ├── messaging.py     ← WebSocket broadcast + state-builder registry
│   │   ├── state_builder.py ← Core participant/host state fields (mode, scores, participants)
│   │   ├── auth.py          ← HTTP Basic Auth middleware
│   │   ├── names.py         ← Character name pool for conference mode (251 names)
│   │   ├── metrics.py       ← Prometheus custom metrics (connections, votes, Q&A)
│   │   └── version.py       ← Backend version detection from static/version.js
│   └── features/            ← One sub-package per feature; each has router.py + optional state_builder.py
│       ├── internal/        ← Internal/admin endpoints
│       ├── pages/           ← HTML page serving (/, /host, /notes)
│       ├── session/         ← Session lifecycle + snapshot/restore for daemon persistence
│       ├── slides/          ← Slides navigation, Drive sync, upload/publish
│       ├── upload/          ← File upload handling
│       └── ws/              ← WebSocket endpoint /ws/{uuid}, /ws/daemon
├── daemon/                  ← Training daemon (runs on host's Mac)
│   ├── __main__.py          ← Daemon entry point + orchestrator loop
│   ├── config.py            ← Env vars and defaults
│   ├── http.py              ← Shared HTTP helper (Basic Auth headers)
│   ├── log.py               ← Shared logging format (HH:MM:SS.f PID [name])
│   ├── session_state.py     ← Session stack management + disk persistence
│   ├── lock.py              ← PID file lock (single instance)
│   ├── llm/adapter.py       ← Claude API wrapper with token counting & cost tracking
│   ├── quiz/                ← Quiz generation: generator.py, history.py, poll_api.py
│   ├── debate/ai_cleanup.py ← AI deduplication and cleanup of debate arguments
│   ├── summary/             ← Live transcript summarization: summarizer.py, loop.py
│   ├── transcript/          ← Transcript reading: parser, loader, query, rebuild, session, state
│   ├── slides/              ← PPTX→PDF: daemon.py, catalog.py, convert.py,
│   │                           drive_sync.py, upload.py, loop.py
│   ├── materials/           ← Project file mirroring: mirror.py, ws_runner.py
│   └── rag/                 ← RAG: indexer.py, retriever.py, project_files.py
├── tests/                   ← See [TESTING.md](TESTING.md) for test rules and structure
├── pyproject.toml           ← Python dependencies (used by Railway via uv)
├── static/
│   ├── participant.html     ← Participant-facing page
│   ├── participant.js       ← Participant logic (WS, voting, Q&A, debate, codereview, emoji)
│   ├── participant.css
│   ├── host.html            ← Host control panel
│   ├── host.js              ← Host logic (WS, poll/activity management, debate control)
│   ├── host.css
│   ├── common.css           ← Shared CSS variables
│   ├── notes.html           ← Read-only notes & summary display page
│   ├── version.js           ← Generated at deploy time (not committed)
│   ├── version-age.js       ← Version age display in corner
│   ├── version-reload.js    ← Auto-reload on version change
│   └── work-hours.js        ← Work hours utility (do not auto-edit)
└── docs/
    ├── seq/                     ← Sequence diagrams (PlantUML)
    │   ├── seq_debate_flow.puml
    │   ├── seq_quiz_flow.puml
    │   ├── seq_slides_*.puml
    │   └── seq_summary_flow.puml
    ├── participant-ws.yaml      ← AsyncAPI spec: participant WS events (contract-tested)
    ├── host-ws.yaml             ← AsyncAPI spec: host WS events (contract-tested)
    └── openapi-generated.yaml   ← OpenAPI snapshot: daemon REST endpoints (contract-tested)
```
- All C4 diagrams (C1, C2, C3) and the system interactions sequence diagram are inlined in [ARCHITECTURE.md](ARCHITECTURE.md).
---

## AppState model

```python
class AppState:
    # Poll
    poll: dict | None                           # {id, question, multi, correct_count, options[], source, page}
    poll_active: bool
    votes: dict[str, str | list]                # uuid → option_id or [option_ids] (multi-select)
    poll_opened_at: datetime | None
    poll_correct_ids: list[str] | None
    vote_times: dict[str, datetime]             # uuid → vote timestamp (speed-based scoring)
    # Participants
    participants: dict[str, WebSocket]          # uuid → ws connection
    participant_names: dict[str, str]           # uuid → display_name (mutable via set_name)
    participant_avatars: dict[str, str]          # uuid → avatar filename or "letter:XX:color"
    participant_universes: dict[str, str]        # uuid → universe string (conference mode)
    locations: dict[str, str]                   # uuid → location string (city/country or timezone)
    # Scores
    scores: dict[str, int]                      # uuid → total score
    base_scores: dict[str, int]                 # uuid → score at poll open (for speed calculation)
    # Activity tracking
    current_activity: ActivityType              # NONE|POLL|WORDCLOUD|QA|DEBATE|CODEREVIEW
    # Word Cloud
    wordcloud_words: dict[str, int]             # word → count
    wordcloud_topic: str
    # Q&A
    qa_questions: dict[str, dict]               # qid → {id, text, author, upvoters: set, answered, timestamp}
    # Code Review
    codereview_snippet: str | None
    codereview_language: str | None
    codereview_phase: str                       # "idle"|"selecting"|"reviewing"
    codereview_selections: dict[str, set[int]]  # uuid → set of selected line numbers
    codereview_confirmed: set[int]              # lines host confirmed as correct
    # Debate
    debate_statement: str | None
    debate_phase: str | None                    # "side_selection"|"arguments"|"ai_cleanup"|"prep"|"live_debate"|"ended"
    debate_sides: dict[str, str]                # uuid → "for"|"against"
    debate_arguments: list[dict]                # [{id, author_uuid, side, text, upvoters: set, ai_generated, merged_into}]
    debate_champions: dict[str, str]            # "for"|"against" → uuid
    debate_auto_assigned: set[str]              # uuids auto-assigned to balance sides
    debate_first_side: str | None               # "for"|"against" — which speaks first
    debate_round_index: int | None              # 0-3 for live rounds
    debate_round_timer_seconds: int | None
    debate_round_timer_started_at: datetime | None
    debate_ai_request: dict | None              # pending AI cleanup payload for daemon
    # Leaderboard
    leaderboard_active: bool                    # is leaderboard overlay visible?
    # Quiz (daemon integration)
    quiz_request: dict | None                   # {minutes: int|None, topic: str|None}
    quiz_refine_request: dict | None            # {target: "question"|"optN"}
    quiz_status: dict | None                    # {status, message}
    quiz_preview: dict | None                   # {question, options[], multi, correct_indices[]}
    daemon_last_seen: datetime | None
    daemon_session_folder: str | None
    daemon_session_notes: str | None
    # Summary & Notes
    summary_points: list[dict]                  # [{text, source: "notes"|"discussion", time: "HH:MM"}]
    summary_updated_at: datetime | None
    summary_force_requested: bool
    notes_content: str | None
    # Transcript tracking
    transcript_line_count: int                  # lines processed
    transcript_total_lines: int                 # total lines in file
    transcript_latest_ts: str | None            # latest timestamp
    # Token usage (LLM cost tracking)
    token_usage: dict                           # {input_tokens, output_tokens, estimated_cost_usd}
    # Mode
    mode: str                                   # "workshop"|"conference"
```

All state dicts are keyed by **UUID**, not display name. Duplicate display names are allowed.

---

## Key Design Decisions

- **No venv**: dependencies installed globally into system Python 3.12 on Mac; `python3 quiz_generator.py` runs directly
- **Host auth scope**: protected endpoints: `/host`, `/api/poll`, `/api/poll/status`, `/api/poll/correct`, `/api/poll/timer`, `/api/scores`, `/api/quiz-*`, `/api/summary` (POST), `/api/notes` (POST), `/api/transcript-status`, `/api/summary/force` (GET, daemon poll), `/api/token-usage`, `/api/codereview`, `/api/codereview/status`, `/api/codereview/confirm-line`, `/api/wordcloud/topic`, `/api/wordcloud/clear`, `/api/activity`, `/api/qa/*`, `/api/debate/*`, `/api/leaderboard/*`, `/api/mode`, `/metrics`; public endpoints: `/`, `/notes`, `/api/suggest-name`, `/api/status`, `/api/summary` (GET), `/api/notes` (GET), `/api/summary/force` (POST, 30s cooldown); Q&A submit/upvote and debate interactions via WebSocket only
- **UUID-based identity**: participants identified by UUID (not name). WebSocket route: `/ws/{uuid}`. First WS message must be `set_name`. Host cookie (`is_host=1`) switches UUID storage to `sessionStorage` for multi-tab testing. Duplicate display names allowed.
- **Personalized broadcasts**: each participant receives `my_score`, `is_own`, `has_upvoted` fields. Host receives `participants` as a list of `{uuid, name, score, location}` objects.
- **Votes are final**: once a participant votes, they cannot change their vote. This is intentional.
- **No persistence between sessions**: restarting the server clears all state. Acceptable because sessions are live events.
- **Quiz correct_indices**: stored in the quiz JSON for trainer preview only — never sent to the poll server
- **Disabled buttons on empty input**: whenever a text input is paired with a submit button, the button must be `disabled` when the input is empty/whitespace-only. Use `oninput` to toggle `disabled`, and re-disable after programmatic `input.value = ''` in the submit function. This applies to all input+button pairs across host and participant (Q&A, word cloud, debate arguments, etc.).
- **Consistent tab button styling**: all host tab-bar buttons (Poll, Words, Q&A, Code, Debate, Board) must share the same visual treatment — transparent background, no border, same hover/active states via `.tab-btn` class. Do not add special backgrounds, borders, or colors to individual tab buttons. Layout differences (e.g. `margin-left:auto` for right-alignment) are acceptable but visual style must be uniform.
- **Summary generation is on-demand only**: no periodic timer. Triggered by host (🧠 badge click) or participant (Key Points button). `POST /api/summary/force` is public (no auth) with 30s cooldown.
- **`static/work-hours.js` ownership**: do not auto-update or edit this file in agent tasks; it is updated manually by the project owner.

---

## Training Daemon (`training_daemon.py`)

Orchestration daemon running on the trainer's Mac:
- Long-polls the backend for quiz requests, debate AI cleanup, and summary force requests
- Reads normalized transcript files from local disk (produced by `victor-macos-addons` repo which handles live Whisper transcription)
- Quiz generation: reads last N minutes of transcript, sends to Claude API, posts preview to backend
- Quiz refinement: regenerates specific question/option on host request
- Debate AI cleanup: deduplicates, fixes typos, suggests new arguments via Claude
- Live summary: reads transcript on demand, generates key points via Claude, posts to backend
- Auto-update: exit code 42 signals wrapper script to git pull + restart
- `ANTHROPIC_API_KEY` is set in the environment
- Run: `python3 training_daemon.py`
- Uses `daemon/` subpackage: `llm_adapter.py`, `summarizer.py`, `debate_ai.py`, `transcript_state.py`, `transcript_query.py`, `indexer.py`, `rag.py`, `project_files.py`

> **Note:** Live audio transcription (Whisper, audio capture, transcript normalization/writing) has been moved to the [`victor-macos-addons`](https://github.com/victorrentea/victor-macos-addons) repo. This daemon only reads the normalized transcript files produced by that tool.

Manual normalized transcript query (run only on demand):
- Script: `python3 -m daemon.transcript_query <from_iso> <to_iso>`
- Input format: strict ISO datetime with `T` separator (`YYYY-MM-DDTHH:MM[:SS]`)
- Source files: normalized daily files only (`YYYY-MM-DD transcription.txt`)
- Output: all matching lines + a final range/line-count footer
- Example:
  - `python3 -m daemon.transcript_query 2026-03-25T12:00:00 2026-03-26T09:30:00`
- Common usage patterns:
  - “today so far” -> `python3 -m daemon.transcript_query "$(date +%Y-%m-%d)T00:00:00" "$(date +%Y-%m-%dT%H:%M:%S)"`
  - “last 10 minutes” -> `python3 -m daemon.transcript_query "$(date -v-10M +%Y-%m-%dT%H:%M:%S)" "$(date +%Y-%m-%dT%H:%M:%S)"`

Manual rebuild utility (run only on demand):
- Script: `python3 -m daemon.rebuild_normalized_transcripts --from-iso <iso_datetime>`
- Purpose: reset normalizer state and regenerate all normalized transcripts from raw transcript files.
- Safety: creates backup folder in `TRANSCRIPTION_FOLDER` before rebuild (`.backup-normalized-YYYYMMDD-HHMMSS`).
- Effects:
  - removes old normalized files (`YYYY-MM-DD transcription.txt`)
  - removes old offset files (`normalization.offset.txt`, legacy `*.txt.offset`)
  - re-runs normalization across all raw transcript files
- Example:
  - `python3 -m daemon.rebuild_normalized_transcripts --from-iso 2026-03-24T09:30:00`

---

## Local Development

```bash
pip3 install fastapi "uvicorn[standard]" websockets python-multipart anthropic
python3 -m uvicorn railway.app:app --reload --port 8000
```

- Host panel:   http://localhost:8000/host
- Participant:  http://localhost:8000/
- API docs:     http://localhost:8000/docs

---

## Memory

Whenever the user says "remember" or asks you to remember something, add it to this file (CLAUDE.md).
Only add memories when explicitly asked, or after the user has confirmed the information is correct (human-in-the-loop). Do not proactively save assumptions or inferences.

- User has Railway CLI installed and available in terminal.
- For any change to the training daemon ("demon"), push directly to `master` because the daemon continuously pulls from `master` and runs those changes.
- PPTX slides daemon logs must follow the shared daemon pattern from `daemon/log.py`: `HH:MM:SS.f PID [name      ] info|error message` (use component name `slides`, not custom `[pptx-daemon]` prefixes).
- There is a course catalog and a slides catalog file in this project that maps course names to local disk paths of the associated PowerPoint presentations.
- User wants every completed task pushed to `master` immediately.
- Session model (source of truth for future changes): no session stack model; exactly one active session at a time. Host activates one session, it becomes active; host stops it, then can activate another.
- `daemon_state.json` is the source of truth for which session is currently active.
- Session links must remain stable across days: each session has a unique persistent `session_id`, and participants can reuse the same link whenever host restarts/resumes that session (today, tomorrow, or weeks later).
- Slow hermetic tests (>5s) must be tagged `@pytest.mark.nightly` so they are excluded from every-push CI (`-m "not nightly"` is the default Docker CMD) and run only in the nightly build (`.github/workflows/nightly.yml`, 03:00 UTC, also triggerable via `workflow_dispatch`). To run manually: `bash tests/docker/build-daemon.sh -m nightly -v --tb=long -s`.
- Use strict FastAPI + Pydantic contracts for daemon APIs and WS messages; avoid raw dict payload sends when a typed message model exists.

---

## Communication Notes

The user frequently uses a dictation tool. Messages may contain misheard or mistyped words (e.g. "non-mina team" for "Nominatim", "entropic" for "Anthropic"). Use context to infer the intended meaning rather than taking words literally.

---

## Workflow

- **After completing each backlog item**: create a git commit and push directly to master (no PR needed for this project).
- **After completing each backlog item**: attach proof before marking it done (screenshot evidence by default; for non-visual tasks, include equivalent captured proof such as test output/logs).
- **Deploy monitoring**: `./watch-deploy.sh` runs continuously in the background (started once per work session). It writes a heartbeat to `/tmp/watch_deploy.lock` (JSON with `pid` and `heartbeat` epoch). **After creating a PR**, check the lock file: read the JSON, verify the PID is alive (`kill -0`) and heartbeat is fresh (<15s). If running, praise the user ("Deploy watcher is running"). If not running or stale, warn and suggest: `./watch-deploy.sh &`
- **After any significant architectural change**: update the C4 diagrams (C1, C2, C3) and system interactions sequence diagram inlined in [ARCHITECTURE.md](ARCHITECTURE.md) to reflect the new structure.
- **After any change to inter-system communication** (WebSocket messages, REST endpoints, HTTP calls between backend/daemon/frontend/overlay/external services): update the "System Interactions" sequence diagram inlined in [ARCHITECTURE.md](ARCHITECTURE.md) to keep it in sync with the code. This includes adding, removing, or renaming WS message types, HTTP endpoints, or changing which component initiates a flow.
- **Running tests**: always use the convenience scripts instead of raw pytest commands: `bash tests/check-all.sh` (quick verify), `bash tests/run-daemon-tests.sh` (daemon only), `bash tests/docker/run-hermetic.sh` (full Docker hermetic, ~10 min, output → `logs/`). These avoid permission prompts and ensure correct flags.
- **Test-Drive-Fix any human-reported bug**: see [TESTING.md](TESTING.md) for the full protocol.
- **E2E = hermetic**: when the user says "E2E test" or "end-to-end test", they mean a **hermetic Docker test** (`tests/docker/`): real backend + real daemon (stub adapters) + Playwright browsers, all in one container. The goal is to migrate all existing `tests/e2e/` tests into hermetic tests. See [TESTING.md](TESTING.md) for infrastructure details.
- **Document direct request**: Every time the human requests a feature change or bug fix after you do it, keep track of it in backlog.md in a concise way as being done.


## Workflow Orchestration
### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update tasks/lessons.md with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: “Would a staff engineer approve this?”
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask “is there a more elegant way?”
- If a fix feels hacky: “Knowing everything I know now, implement the elegant solution”
- Skip this for simple, obvious fixes – don’t over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don’t ask for hand-holding
- Point at logs, errors, failing tests – then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management
1.	Plan First: Write plan to tasks/todo.md with checkable items
2.	Verify Plan: Check in before starting implementation
3.	Track Progress: Mark items complete as you go
4.	Explain Changes: High-level summary at each step
5.	Document Results: Add review section to tasks/todo.md
6.	Capture Lessons: Update tasks/lessons.md after corrections

## Core Principles
- Simplicity First: Make every change as simple as possible. Impact minimal code.
- No Laziness: Find root causes. No temporary fixes. Senior developer standards.
- Minimal Impact: Only touch what’s necessary. No side effects with new bugs.
