# Workshop Live Interaction Tool — Project Context

This document captures all requirements, decisions, and context for the project.
It is intended as the primary reference for any AI coding assistant working on this codebase.

---

## Project Goal

Build a **self-hosted, real-time audience interaction tool** for use during online webinars and workshops. The host (facilitator) controls the session from a dedicated panel; participants join via a shared browser link with no installation required. The tool must work reliably with groups of 30–150 concurrent participants.

---

## Functional Requirements

### Participant experience
- Join a session by opening a URL in any browser — **no app install, no account, no login**
- Set a display name on first visit; the name is **persisted in `localStorage`** and pre-filled on return visits from the same browser
- Interact with live activities (polls, future: Q&A, word cloud) in real time
- See results update live without any page reload

### Host experience
- Single host control panel at `/host`
- Create, open, close, and remove polls
- See live vote counts and results as participants vote
- See connected participant count in real time

### Session model
- **Single active room** at any time — no multi-room, no session codes
- State is **in-memory** (Python dict); no database required
- State resets on server restart — this is acceptable (sessions are short, live events)

---

## Interaction Features

### Phase 1 — implemented in scaffold
- **Live Poll**: host creates a question with 2–8 options; participants vote once; results shown as animated bar charts updating in real time for everyone

### Phase 2 — planned, not yet implemented
- **Q&A with upvoting**: participants submit questions; others can upvote; host sees ranked list
- **Word cloud**: participants submit one or more words; host displays an animated word cloud

### Phase 3 — future AI integration
- Claude API (or other LLM) integration for Q&A summarisation, automated responses, or word cloud insights
- To be added as FastAPI background endpoints; Anthropic API calls via serverless-style route handlers

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
| Language | **Python 3.12** | Developer is also comfortable with Java and Spring Boot, but chose Python to learn something new |
| Framework | **FastAPI** | Async, WebSocket support native, auto Swagger UI at `/docs` |
| Real-time transport | **WebSockets** (native FastAPI) | One persistent WS connection per participant; server broadcasts state changes |
| State storage | **In-memory Python dict** | Sufficient for single-room, short-duration live sessions |
| ASGI server | **Uvicorn** | Run with `uvicorn main:app --host 0.0.0.0 --port 8000` |

### Frontend
| Concern | Choice | Notes |
|---|---|---|
| Language | **Vanilla JavaScript (ES6+)** | No framework, no build step |
| Markup | **Plain HTML5** | Single-file pages per role |
| Styling | **Inline CSS** (per file) | Dark theme, CSS variables, no external CSS framework |
| Participant name persistence | **`localStorage`** | Key: `workshop_participant_name` |
| WebSocket client | **Native browser WebSocket API** | Auto-reconnect on disconnect (3s retry) |

### Infrastructure
| Concern | Choice | Notes |
|---|---|---|
| Hosting | **Oracle Cloud Infrastructure (OCI) Free Tier** | ARM Ampere A1 VM — always-on, permanently free, up to 4 OCPUs / 24 GB RAM |
| OS | Ubuntu (ARM) | Standard OCI free VM |
| Reverse proxy | **nginx** | Handles HTTP + WebSocket upgrade, proxies to Uvicorn on port 8000 |
| Process management | **systemd** | `workshop.service` unit file included; auto-restarts on failure |
| HTTPS | Let's Encrypt via `certbot --nginx` | Not yet configured in scaffold — recommended before production use |

### Why OCI over alternatives
- **AWS Free Tier**: EC2 t3.micro is free for 12 months only, then paid — rejected
- **Fly.io**: removed free tier for new users in 2024 (7-day trial only) — rejected
- **Render / Railway**: free tiers spin down after inactivity (30–60s cold start) — rejected (cold starts are a hard no-go requirement)
- **OCI Always Free**: permanent, no expiry, no sleep, 10 TB/month outbound — selected

---

## Project Structure

```
workshop-tool/
├── main.py                  ← FastAPI application (all backend logic)
├── requirements.txt         ← Python dependencies
├── static/
│   ├── participant.html     ← Participant-facing page (join + vote)
│   └── host.html            ← Host control panel
├── workshop.service         ← systemd unit file for OCI deployment
├── nginx.conf               ← nginx reverse proxy config (WebSocket-aware)
└── README.md                ← Local run + OCI deploy instructions
```

---

## Architecture Overview

```
Browser (participant)          Browser (host)
        │                            │
        │  WebSocket /ws/{name}      │  WebSocket /ws/__host__
        │  GET /                     │  GET /host
        │  (vote messages)           │  POST /api/poll
        │                            │  POST /api/poll/status
        └──────────┬─────────────────┘
                   │ nginx (port 80 / 443)
                   │ proxy_pass + WebSocket upgrade headers
                   ▼
         Uvicorn (port 8000)
         FastAPI app — main.py
                   │
           AppState (in-memory)
           ├── poll: dict | None
           ├── poll_active: bool
           ├── votes: dict[name → option_id]
           └── participants: dict[name → WebSocket]
```

### Real-time flow
1. Participant connects via WebSocket → server sends full current state immediately
2. Host creates/opens/closes poll via REST API → server broadcasts updated state to **all** connected WebSocket clients
3. Participant votes → server updates `votes` dict → broadcasts `vote_update` to all clients
4. Any disconnect → server removes from `participants` dict → broadcasts updated participant count

---

## Key Design Decisions

- **Single room, no auth on scaffold**: the host panel at `/host` has no password in the current scaffold. Adding HTTP Basic Auth via nginx or a token check in FastAPI is a recommended next step before public deployment.
- **Host connects as a WebSocket participant too** (name `__host__`) so the host panel receives live state broadcasts without polling.
- **Votes are final**: once a participant votes, they cannot change their vote. This is intentional.
- **No persistence between sessions**: restarting the server clears all state. Acceptable because sessions are live events, not async.
- **ARM architecture**: OCI free VM is ARM (Ampere A1). Python + FastAPI run natively on ARM with no changes.

---

## Dependencies

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
websockets==14.1
python-multipart==0.0.20
```

---

## Local Development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r dependencies.txt
uvicorn main:app --reload --port 8000
```

- Host panel:   http://localhost:8000/host
- Participant:  http://localhost:8000/
- API docs:     http://localhost:8000/docs

---

## Backlog / Next Steps

- [ ] Add host authentication (nginx Basic Auth or FastAPI token middleware)
- [ ] Add HTTPS via Let's Encrypt (`certbot --nginx`)
- [ ] Implement Q&A feature with upvoting (Phase 2)
- [ ] Implement word cloud feature (Phase 2)
- [ ] Add session history / export (optional)
- [ ] Claude API integration for AI-assisted Q&A summarisation (Phase 3)