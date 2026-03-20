# Workshop Live Interaction Tool — Project Context

This document captures all requirements, decisions, and context for the project.
It is intended as the primary reference for any AI coding assistant working on this codebase.

**Core product goal:** Maximize audience engagement during live workshops and webinars. The target audience is tired, bored, and distracted. Every feature should serve this goal — competition, real-time feedback, and interactivity are not nice-to-haves, they are the point.

---

## Secrets

Host panel credentials are stored in `secrets.env` (gitignored — never commit this file).
The file contains `HOST_USERNAME` and `HOST_PASSWORD` for accessing `/host` and `/api/poll`, `/api/poll/status`, `/api/qa/question/{id}` (PATCH, DELETE), `/api/qa/answer/{id}`, `/api/qa/clear`, `/api/activity`, `/api/wordcloud/clear`.

---

## Production Deployment

- **URL**: https://interact.victorrentea.ro
- **Platform**: [Railway](https://railway.app) — auto-deploys on every push to `master`
- **Deploy**: `git push` to `master` → Railway builds and deploys in ~40-50 seconds. No manual steps.
- **Auth**: HTTP Basic Auth on `/host`, `/api/poll`, `/api/poll/status`, `/api/qa/question/{id}` (PATCH, DELETE), `/api/qa/answer/{id}`, `/api/qa/clear`, `/api/activity`, `/api/wordcloud/clear` — participants access `/`, `/api/suggest-name`, `/api/status`, `/api/qa/question` (POST), `/api/qa/upvote` freely
- **Versioning**: a pre-commit git hook stamps `static/version.js` with the current timestamp; both host and participant pages display it in the bottom-right corner

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

### Phase 2 — planned, not yet implemented
- **Q&A with upvoting**: participants submit questions; others can upvote; host sees ranked list
- **Word cloud**: participants submit one or more words; host displays an animated word cloud

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
| Participant name persistence | **`localStorage`** | Key: `workshop_participant_name` |
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
├── main.py                  ← FastAPI application (all backend logic)
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
    poll: dict | None          # current poll definition
    poll_active: bool          # is voting open?
    votes: dict[str, str]      # participant_name -> option_id
    participants: dict[str, WebSocket]  # name -> ws
    suggested_names: set[str]  # names handed out but not yet connected
    locations: dict[str, str]  # participant_name -> location string (city/country or timezone)
```

---

## Key Design Decisions

- **No venv**: dependencies installed globally into system Python 3.12 on Mac; `python3 quiz_generator.py` runs directly
- **Host auth scope**: protected endpoints: `/host`, `/api/poll`, `/api/poll/status`, `/api/qa/question/{id}` (PATCH, DELETE), `/api/qa/answer/{id}`, `/api/qa/clear`, `/api/activity`, `/api/wordcloud/clear`; public endpoints: `/api/suggest-name`, `/api/status`, `/api/qa/question` (POST), `/api/qa/upvote`
- **Votes are final**: once a participant votes, they cannot change their vote. This is intentional.
- **No persistence between sessions**: restarting the server clears all state. Acceptable because sessions are live events.
- **Quiz correct_indices**: stored in the quiz JSON for trainer preview only — never sent to the poll server

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
- **Deploy monitoring**: `./watch-deploy.sh` runs continuously in the background (started once per work session). It polls GitHub master HEAD every 10s and production every 2s. On merge detection, it waits up to 2 min for deploy, then fires a macOS notification (success or timeout). **After creating a PR**, remind the user to start the watcher if not already running: `./watch-deploy.sh &`
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