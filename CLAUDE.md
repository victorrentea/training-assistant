# Workshop Live Interaction Tool — Project Context

This document captures all requirements, decisions, and context for the project.
It is intended as the primary reference for any AI coding assistant working on this codebase.

**Core product goal:** Maximize audience engagement during live workshops and webinars. The target audience is tired, bored, and distracted. Every feature should serve this goal — competition, real-time feedback, and interactivity are not nice-to-haves, they are the point.

---

## Secrets

Host panel credentials are stored in `secrets.env` (gitignored — never commit this file).
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

---

## Technology Stack

### Backend
| Concern | Choice | Notes |
|---|---|---|
| Language | **Python 3.12** | Local dev and Railway both use Python 3.12 |
| Framework | **FastAPI** | Async, WebSocket support native, auto Swagger UI at `/docs` |
| Real-time transport | **WebSockets** (native FastAPI) | One persistent WS connection per participant; server broadcasts state changes |
| State storage | **In-memory Python dict** | Sufficient for single-room, short-duration live sessions |
| ASGI server | **Uvicorn** | `python3 -m uvicorn main:app --host 127.0.0.1 --port 8000` |

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
├── main.py                  ← FastAPI application (entry point, mounts routers)
├── names.py                 ← Character name pool for conference mode (251 names from movies/games)
├── routers/
│   ├── codereview.py        ← Code Review activity (snippet broadcast, line selection, confirm)
│   ├── leaderboard.py       ← Leaderboard show/hide endpoints (host-only)
├── dependencies.txt         ← Python dependencies
├── quiz_generator.py        ← Companion CLI: reads transcription, generates quiz via Claude API
├── quiz_config.example.env  ← Template for quiz generator env vars
├── secrets.env              ← (gitignored) Host panel credentials
├── static/
│   ├── participant.html     ← Participant-facing page (join + vote)
│   ├── participant.js       ← Participant logic (WS, voting, geolocation)
│   ├── participant.css
│   ├── host.html            ← Host control panel
│   ├── host.js              ← Host logic (WS, poll management, participant list)
│   ├── host.css
│   └── common.css           ← Shared CSS variables
└── pyproject.toml           ← Python dependencies (used by Railway via uv)
```
- For further architectural details, see the adoc folder. 
---

## AppState model

```python
class AppState:
    poll: dict | None                           # current poll definition
    poll_active: bool                           # is voting open?
    participants: dict[str, WebSocket]          # uuid → ws connection
    participant_names: dict[str, str]           # uuid → display_name (mutable via set_name)
    participant_avatars: dict[str, str]          # uuid → avatar filename (assign-once)
    votes: dict[str, str]                       # uuid → option_id (or list for multi-select)
    locations: dict[str, str]                   # uuid → location string (city/country or timezone)
    scores: dict[str, int]                      # uuid → score
    base_scores: dict[str, int]                 # uuid → base score (speed calculations)
    vote_times: dict[str, datetime]             # uuid → vote timestamp (speed-based scoring)
    qa_questions: dict[str, dict]               # question_id → {author: uuid, upvoters: set[uuid], ...}
    codereview_snippet: str | None              # current code snippet
    codereview_language: str | None             # auto-detected or overridden language
    codereview_phase: str                       # "idle" | "selecting" | "reviewing"
    codereview_selections: dict[str, set[int]]  # uuid → set of selected line numbers
    codereview_confirmed: set[int]              # lines host confirmed as correct
    leaderboard_active: bool                    # is leaderboard overlay visible?
    participant_universes: dict[str, str]        # uuid → universe string (conference mode)
```

All state dicts are keyed by **UUID**, not display name. Duplicate display names are allowed.

---

## Key Design Decisions

- **No venv**: dependencies installed globally into system Python 3.12 on Mac; `python3 quiz_generator.py` runs directly
- **Host auth scope**: protected endpoints: `/host`, `/api/poll`, `/api/poll/status`, `/api/qa/question/{id}` (PATCH, DELETE), `/api/qa/answer/{id}`, `/api/qa/clear`, `/api/activity`, `/api/wordcloud/clear`, `/api/codereview`, `/api/codereview/status`, `/api/codereview/confirm-line`, `/api/mode`, `/api/leaderboard/show`, `/api/leaderboard/hide`; public endpoints: `/api/suggest-name`, `/api/status`; Q&A submit/upvote via WebSocket only
- **UUID-based identity**: participants identified by UUID (not name). WebSocket route: `/ws/{uuid}`. First WS message must be `set_name`. Host cookie (`is_host=1`) switches UUID storage to `sessionStorage` for multi-tab testing. Duplicate display names allowed.
- **Personalized broadcasts**: each participant receives `my_score`, `is_own`, `has_upvoted` fields. Host receives `participants` as a list of `{uuid, name, score, location}` objects.
- **Votes are final**: once a participant votes, they cannot change their vote. This is intentional.
- **No persistence between sessions**: restarting the server clears all state. Acceptable because sessions are live events.
- **Quiz correct_indices**: stored in the quiz JSON for trainer preview only — never sent to the poll server
- **Disabled buttons on empty input**: whenever a text input is paired with a submit button, the button must be `disabled` when the input is empty/whitespace-only. Use `oninput` to toggle `disabled`, and re-disable after programmatic `input.value = ''` in the submit function. This applies to all input+button pairs across host and participant (Q&A, word cloud, debate arguments, etc.).

---

## Quiz Generator (`quiz_generator.py`)

Companion CLI that runs on the trainer's Mac:
- Reads transcription files from `/Users/victorrentea/Documents/transcriptions/`
- Format: `[HH:MM:SS.xx] Speaker:\ttext` (also supports .vtt and .srt)
- Extracts last N minutes (default 30), sends to Claude API
- Generates a debate-triggering poll question with `correct_indices` for trainer reference only
- Interactive feedback loop: preview → refine option → post to server
- `ANTHROPIC_API_KEY` is set in the environment
- Run: `python3 quiz_generator.py [--minutes 30] [--dry-run]`

---

## Local Development

```bash
pip3 install fastapi "uvicorn[standard]" websockets python-multipart anthropic
python3 -m uvicorn main:app --reload --port 8000
```

- Host panel:   http://localhost:8000/host
- Participant:  http://localhost:8000/
- API docs:     http://localhost:8000/docs

---

## Memory

Whenever the user says "remember" or asks you to remember something, add it to this file (CLAUDE.md).
Only add memories when explicitly asked, or after the user has confirmed the information is correct (human-in-the-loop). Do not proactively save assumptions or inferences.

---

## Communication Notes

The user frequently uses a dictation tool. Messages may contain misheard or mistyped words (e.g. "non-mina team" for "Nominatim", "entropic" for "Anthropic"). Use context to infer the intended meaning rather than taking words literally.

---

## Workflow

- **After completing each backlog item**: create a git commit.
- **After completing each backlog item**: attach proof before marking it done (screenshot evidence by default; for non-visual tasks, include equivalent captured proof such as test output/logs).
- **Deploy monitoring**: `./watch-deploy.sh` runs continuously in the background (started once per work session). It writes a heartbeat to `/tmp/watch_deploy.lock` (JSON with `pid` and `heartbeat` epoch). **After creating a PR**, check the lock file: read the JSON, verify the PID is alive (`kill -0`) and heartbeat is fresh (<15s). If running, praise the user ("Deploy watcher is running"). If not running or stale, warn and suggest: `./watch-deploy.sh &`
- **After any significant architectural change**: update the C4 diagrams in `adoc/` (c4_c1_context.puml, c4_c2_containers.puml, c4_c3_components.puml) to reflect the new structure.
- **Test-Drive-Fix any human-reported bug**: start by reproducing the bug yourself manually, then write an automated test for the bug, see it failing, then passing after you fixed the bug.
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