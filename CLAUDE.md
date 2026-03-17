# Workshop Live Interaction Tool — Project Context

This document captures all requirements, decisions, and context for the project.
It is intended as the primary reference for any AI coding assistant working on this codebase.

---

## Secrets

Host panel credentials are stored in `secrets.env` (gitignored — never commit this file).
The file contains `HOST_USERNAME` and `HOST_PASSWORD` for accessing `/host` and `/api/poll`, `/api/poll/status`.

---

## Production Deployment

- **URL**: https://interact.victorrentea.ro
- **Server**: Oracle Cloud Infrastructure (OCI) Free Tier VM
  - IP: `141.148.230.245`
  - OS: Oracle Linux 9 (x86_64) — **not** Ubuntu/ARM as originally planned
  - RAM: ~500 MB — `dnf` gets OOM-killed; avoid installing packages with dnf
  - SSH: `ssh -i '/Users/victorrentea/My Drive/Clients/oracle-cloud-ssh-key-2026-03-17.key' opc@141.148.230.245`
  - Username: `opc` (not `ubuntu`)
- **App location on server**: `/home/opc/workshop/`
- **Process manager**: systemd — `workshop.service` runs uvicorn, `caddy.service` runs the reverse proxy
- **Reverse proxy**: **Caddy** (not nginx — nginx couldn't be installed due to OOM kills)
  - Binary: `/usr/local/bin/caddy`
  - Config: `/etc/caddy/Caddyfile`
  - SELinux label required: `sudo chcon -t bin_t /usr/local/bin/caddy`
  - Handles HTTPS automatically via Let's Encrypt (cert already issued)
- **Firewall**: both `firewalld` (on VM) and OCI Security List must allow ports 80 and 443
- **Auth**: Caddy `basic_auth` on `/host`, `/api/poll`, `/api/poll/status` — participants access `/`, `/api/suggest-name`, `/api/status` freely

### Deploying code changes

Files are deployed via `scp` (no git on server):
```bash
scp -i '/Users/victorrentea/My Drive/Clients/oracle-cloud-ssh-key-2026-03-17.key' \
  -r main.py static \
  opc@141.148.230.245:~/workshop/
ssh -i '/Users/victorrentea/My Drive/Clients/oracle-cloud-ssh-key-2026-03-17.key' opc@141.148.230.245 \
  "sudo systemctl restart workshop"
```

### Updating the Caddyfile

Always write it via `scp` from a local `/tmp/Caddyfile` — never try to write it inline over SSH
(shell variable interpolation corrupts the `$` signs in bcrypt hashes). Steps:
1. Edit `/tmp/Caddyfile` locally
2. `scp` it to `/tmp/Caddyfile` on server
3. `sudo cp /tmp/Caddyfile /etc/caddy/Caddyfile && sudo systemctl restart caddy`

To regenerate the host password hash on the server:
```bash
caddy hash-password --plaintext 'yourpassword'
```

### Rebooting the instance

OCI CLI is configured on the Mac (`~/.oci/config`). Once the API key is registered in the OCI console:
```bash
oci compute instance action \
  --instance-id ocid1.instance.oc1.eu-amsterdam-1.anqw2ljrf5jnacqcydannxrcq2vd4jdzqoekp2774ynooiz4sf2n4tvgopoq \
  --action RESET
```

OCI credentials:
- Tenancy OCID: `ocid1.tenancy.oc1..aaaaaaaafl5vpencs3pjnq4rchplo6xeawi4dduveayvbfeoh4qpftkvqo3q`
- User OCID: `ocid1.user.oc1..aaaaaaaamtnxcgmlffo7d35kxmzkrhi25qpwrhy4nhjvgn56wg2xin47ksea`
- Region: `eu-amsterdam-1`
- API key: `~/.oci/oci_api_key.pem` (public key must be registered in OCI Console → My Profile → API Keys)
- Instance OCID: `ocid1.instance.oc1.eu-amsterdam-1.anqw2ljrf5jnacqcydannxrcq2vd4jdzqoekp2774ynooiz4sf2n4tvgopoq`

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
| Language | **Python 3.9** | Server runs Python 3.9 (Oracle Linux default); local dev uses Python 3.12 |
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
| Hosting | **Oracle Cloud Infrastructure (OCI) Free Tier** | x86_64 VM, always-on, permanently free |
| OS | **Oracle Linux 9** (x86_64) | Note: original plan said Ubuntu/ARM — actual VM is different |
| Reverse proxy | **Caddy** | Single binary, auto HTTPS via Let's Encrypt, replaces nginx (couldn't install due to OOM) |
| Process management | **systemd** | `workshop.service` + `caddy.service`; both enabled and auto-restart |
| HTTPS | **Caddy + Let's Encrypt** | Configured and live; cert auto-renews |
| Auth | **Caddy `basic_auth`** | Protects `/host`, `/api/poll`, `/api/poll/status` only |

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
├── workshop.service         ← systemd unit file
└── nginx.conf               ← (unused — replaced by Caddy)
```

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

- **Caddy instead of nginx**: nginx OOM-killed during dnf install on 500MB RAM VM; Caddy is a single static binary downloaded via curl
- **SELinux**: Oracle Linux 9 runs SELinux in enforcing mode; Caddy binary needs `chcon -t bin_t` to run under systemd
- **No venv**: dependencies installed globally into system Python 3.12 on Mac; `python3 quiz_generator.py` runs directly
- **Caddyfile written via scp**: never write Caddyfile inline over SSH — shell interpolation corrupts bcrypt `$` signs
- **Host auth scope**: only `/host`, `/api/poll`, `/api/poll/status` are protected; `/api/suggest-name` and `/api/status` are public (used by participants)
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

## Backlog / Next Steps

- [ ] Register OCI API key in console to enable `oci` CLI instance reboots
- [ ] Implement Q&A feature with upvoting (Phase 2)
- [ ] Implement word cloud feature (Phase 2)
- [ ] Add session history / export (optional)
- [ ] Claude API integration for AI-assisted Q&A summarisation (Phase 3)
