# Session Folder Persistence — Design Spec

**Date:** 2026-03-25
**Status:** Approved

---

## Goal

Persist session state (participant names, scores, activity state) to disk so it survives server restarts. The primary driver is score continuity: participants must see their accumulated score when they reconnect after a server restart mid-workshop.

---

## File Structure

### `daemon_state.json` (global, at sessions_root root)

Tracks the currently active main session and optional talk. Written immediately on any session change so daemon restarts recover cleanly.

```json
{
  "main": {
    "name": "2026-03-25 WebSecurity",
    "started_at": "2026-03-25T09:00:00",
    "status": "active"
  },
  "talk": {
    "name": "2026-03-25 12:30 talk",
    "started_at": "2026-03-25T12:30:00",
    "status": "active"
  }
}
```

`talk` is `null` when no talk is running. `status` values: `"active"` | `"paused"`.

### Per-session folder

```
2026-03-25 WebSecurity/
  ├── transcript_discussion.md    ← renamed from transcript_keypoints.md
  ├── web_security_notes.txt      ← trainer notes (unchanged)
  └── session_state.json          ← NEW, written every 5s by daemon
```

### `session_state.json` schema

```json
{
  "saved_at": "2026-03-25T14:32:10",
  "participants": {
    "<uuid>": { "name": "Alice", "score": 420, "location": "Bucharest, RO" }
  },
  "activity": "qa",
  "poll": {
    "id": "...", "question": "...", "options": [...],
    "active": false, "votes": {}, "correct_ids": []
  },
  "qa": {
    "questions": [
      { "id": "...", "text": "...", "author": "<uuid>", "upvoters": [], "answered": false }
    ]
  },
  "wordcloud": { "topic": "microservices", "words": { "resilience": 5 } },
  "debate": {
    "statement": "...", "phase": "arguments",
    "sides": {}, "arguments": []
  },
  "codereview": {
    "snippet": "...", "language": "java",
    "phase": "reviewing", "confirmed": [3, 7]
  },
  "token_usage": {
    "input_tokens": 12400, "output_tokens": 3200, "estimated_cost_usd": 0.045
  }
}
```

The daemon writes this file every 5 seconds while a session folder is active. If no folder exists (FRAGILE state), nothing is written.

---

## File Naming: `transcript_keypoints.md` → `transcript_discussion.md`

All references to `transcript_keypoints.md` (in `training_daemon.py`, `daemon/summarizer.py`, and any other consumers) are renamed to `transcript_discussion.md`. The legacy fallback for `key_points.json` is preserved for backward compatibility with existing folders.

---

## Session Lifecycle

### Startup / folder resolution

| Scenario | Behavior |
|---|---|
| 0 folders match today | FRAGILE state: no persistence. Host UI shows blinking yellow CREATE button. |
| 1 folder matches today | Auto-open that session. Load `session_state.json` into AppState. |
| `daemon_state.json` exists with active session | Restore exactly that session (and talk if present). |

"Matches today" means the folder name contains today's date (format `YYYY-MM-DD`) or a date range that spans today.

### Daily timing

| Time | Event |
|---|---|
| 9:00am | Session considered open (auto-open if folder matches today) |
| 5:30pm | Host panel shows 30-min warning: yellow blinking banner *"Recording pauses in 30 min"* |
| 6:00pm | Daemon auto-pauses transcription. Session stays open. |
| Midnight | Session `status` set to `ended` in `daemon_state.json`. |
| Next 9am | Fresh resolution: looks for today's folder. |

After 6pm auto-pause, the host can manually resume, or start a talk (e.g. evening session).

### FRAGILE state (no folder)

- Daemon does not write `session_state.json`
- Live activity works normally (scores tracked in memory only)
- Host panel sessions pane shows:
  - Input pre-filled with `YYYY-MM-DD ` (today's date + space)
  - Host types session name after the date
  - Single yellow blinking **CREATE** button
  - No other buttons shown
- On CREATE: daemon creates the folder, starts session, begins 5s saves immediately (including any state accumulated so far in memory)

### Main session + Talk model

There are always at most **2 sessions**: one `main` (workshop) and one optional `talk` (conference). There is never a third. The talk is always on top.

**START TALK** (button in sessions pane, visible when no talk is active):
1. Auto-creates folder `YYYY-MM-DD HH:MM talk` (current date + time)
2. Saves main session state to its `session_state.json` immediately
3. Switches mode to `conference`
4. Disconnects all main-session participants with `session_paused` message
5. Loads talk's `session_state.json` if the folder already existed (or starts fresh)
6. Writes `daemon_state.json` with `talk` field set

**END TALK** (button in sessions pane, visible when a talk is active):
1. Saves talk state to its `session_state.json`
2. Disconnects all talk participants with `session_paused` message
3. Restores main session state from `session_state.json`
4. Switches mode back to `workshop`
5. Clears `talk` field in `daemon_state.json`
6. Main-session participants (retrying every 5s) are now accepted and reconnect with their scores

---

## Participant UUID Resolution on WebSocket Connect

Every incoming WebSocket connection carries the participant's UUID (from localStorage). The server resolves it against the current session state:

```
UUID in current session's participants?
  YES → welcome back; restore name + score from session_state
  NO, but UUID in other session (main while talk active, or talk while main active)?
    YES → send session_paused message; close WS
  NO (unknown UUID)?
    → new participant for current session
```

The `participants` map in `session_state.json` is the authoritative registry of who belongs to which session.

### "Session paused" participant experience

When a participant's WS is closed with `session_paused`:
- Client receives: `{ "type": "session_paused", "message": "Session paused — you'll reconnect automatically" }`
- Participant page shows a full-screen overlay with that message
- Client retries silently every 5s
- When their session is restored, UUID is recognized → overlay disappears → participant is back with score intact

---

## Host UI Changes

### Sessions pane (right panel)

```
SESSIONS
────────────────────────────────────────
  Talk:  2026-03-25 12:30 talk   [END TALK]   ← blinking yellow border
  Main:  2026-03-25 WebSecurity   ⏸
────────────────────────────────────────
  [ ▶ START TALK ]   ← only when no talk active
  ──────────────────────────────────────
  FRAGILE: [ 2026-03-25 _________ ] [✨ CREATE ✨]
           ← only shown when no folder for today
```

- **Top session (talk)**: blinking yellow border whenever a talk is active (signals nesting to host)
- **⏸ / ▶ button** on main session: pauses/resumes transcription. When paused: button blinks yellow, tooltip *"Not recording"*
- **Rename button**: removed entirely
- **END TALK / START TALK**: mutually exclusive, single button

### Warning banners
- 5:30–6:00pm: yellow blinking banner at top of host panel — *"Recording pauses in 30 min"*
- After 6pm auto-pause: persistent yellow strip — *"Recording paused"* (until host resumes or starts talk)

---

## Restore on Server Restart

1. Daemon detects server is up (via its polling loop)
2. Reads `daemon_state.json` → determines active session(s)
3. Reads `session_state.json` from active session folder
4. Posts restored state to `/api/session/sync` with full payload
5. AppState is populated: participants, scores, activity, poll, qa, wordcloud, debate, codereview, token_usage
6. Participants reconnecting with known UUIDs get their scores back
7. Open activities (QA, wordcloud, etc.) are visible again immediately

---

## Conference Mode Auto-folder

When host switches to conference mode (and no talk is already active):
- Same flow as START TALK
- Folder auto-named `YYYY-MM-DD HH:MM talk`
- No input required

---

## What Does NOT Change

- Transcript file selection logic (by YYYYMMDD in filename)
- Transcript timestamp appending
- Notes file detection (most recent `.txt` in session folder)
- `daemon_state.json` location (sessions_root root)
- Session folder date-range matching logic
- Auto-pause at 6pm / warning at 5:30pm timing logic (new)
- `POST /api/session/sync` endpoint contract (extended with new fields)

---

## Out of Scope

- Three-level session nesting
- Participant self-service session switching
- Talk custom naming (always auto-named `YYYY-MM-DD HH:MM talk`)
- Database persistence (remains in-memory + file)
