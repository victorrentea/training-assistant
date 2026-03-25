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
  "talk": null
}
```

`talk` is `null` when no talk is running. `status` values: `"active"` | `"paused"` | `"ended"`. A session with `status: "ended"` is not restored on daemon startup. Midnight transition sets status to `"ended"` and writes `daemon_state.json`.

### Per-session folder

```
2026-03-25 WebSecurity/
  ├── transcript_discussion.md    ← renamed from transcript_keypoints.md
  ├── web_security_notes.txt      ← trainer notes (unchanged)
  └── session_state.json          ← NEW, written every 5s by daemon
```

### `session_state.json` schema

This file mirrors the full serializable AppState. It is the authoritative restore payload. Fields:

```json
{
  "saved_at": "2026-03-25T14:32:10",
  "mode": "workshop",
  "participants": {
    "<uuid>": {
      "name": "Alice",
      "score": 420,
      "base_score": 380,
      "location": "Bucharest, RO",
      "avatar": "letter:AL:3a86c4",
      "universe": ""
    }
  },
  "activity": "qa",
  "poll": {
    "id": "...", "question": "...", "options": [...], "multi": false,
    "active": false, "votes": {"<uuid>": "<option_id>"},
    "correct_ids": [], "opened_at": null,
    "timer_seconds": null, "timer_started_at": null
  },
  "qa": {
    "questions": [
      { "id": "...", "text": "...", "author": "<uuid>", "upvoters": [], "answered": false, "timestamp": "..." }
    ]
  },
  "wordcloud": {
    "topic": "microservices",
    "words": { "resilience": 5 },
    "word_order": ["resilience"]
  },
  "debate": {
    "statement": "...", "phase": "arguments",
    "sides": {}, "arguments": [],
    "champions": {}, "auto_assigned": [],
    "first_side": null, "round_index": null,
    "round_timer_seconds": null, "round_timer_started_at": null
  },
  "codereview": {
    "snippet": "...", "language": "java",
    "phase": "reviewing", "confirmed": [3, 7],
    "selections": {"<uuid>": [2, 5]}
  },
  "leaderboard_active": false,
  "token_usage": {
    "input_tokens": 12400, "output_tokens": 3200, "estimated_cost_usd": 0.045
  }
}
```

Transient or daemon-owned AppState fields are **not** persisted: `debate_ai_request`, `quiz_request`, `quiz_preview`, `quiz_status`, `quiz_refine_request`, `summary_*`, `notes_content`, `transcript_*`, `daemon_last_seen`, `daemon_session_folder`, `daemon_session_notes`, `session_request`.
```

The daemon writes this file every 5 seconds while a session folder is active. The first write happens immediately when the session starts (not after the first 5s interval), ensuring state accumulated in FRAGILE mode is captured immediately upon folder creation. Write failures are logged as errors but are not fatal. The daemon also performs a final write on clean session end (END TALK, midnight transition).

---

## File Naming: `transcript_keypoints.md` → `transcript_discussion.md`

All references to `transcript_keypoints.md` (in `training_daemon.py`, `daemon/summarizer.py`, and any other consumers) are renamed to `transcript_discussion.md`. The legacy fallback for `key_points.json` is preserved for backward compatibility with existing folders.

---

## Session Lifecycle

### Startup / folder resolution

Resolution runs at **daemon startup** (not at a specific clock time). The order of precedence is:

1. **Check `daemon_state.json` first.** If it exists and has a session with `status: "active"` or `status: "paused"`, restore that session (and talk if present). This takes priority over folder scanning.
2. **If no active session in `daemon_state.json`** (missing file, or status is `"ended"`), fall back to scanning: if exactly 1 folder matches today's date, auto-open it.
3. **If 0 folders match today**: FRAGILE state (no persistence).
4. **If N > 1 folders match today and no `daemon_state.json`**: pick the folder with the latest start date; log a warning.

"Matches today" means the folder name contains today's date (format `YYYY-MM-DD`) or a date range spanning today.

### Daily timing

| Time | Event |
|---|---|
| Daemon startup | Resolve and restore session per precedence rules above |
| 5:30pm | Host panel shows 30-min warning: yellow blinking banner *"Recording pauses in 30 min"* |
| 6:00pm | Daemon auto-pauses transcription. Session stays open (status remains `"active"`). |
| Midnight | Session `status` set to `"ended"` in `daemon_state.json`. Final `session_state.json` written. |
| Next daemon startup | Fresh resolution: looks for today's folder. |

After 6pm auto-pause, the host can manually resume, or start a talk (e.g. evening session).

### FRAGILE state (no folder)

- Daemon does not write `session_state.json`
- Live activity works normally (scores tracked in memory only)
- Host panel sessions pane shows:
  - Input pre-filled with `YYYY-MM-DD ` (today's date + space)
  - Host types session name after the date
  - Single yellow blinking **CREATE** button (no other button shown)
- On CREATE: daemon creates the folder, starts session, begins periodic saves immediately (including any state accumulated so far in memory — first write is immediate, not after 5s)

### Main session + Talk model

There are always at most **2 sessions**: one `main` (workshop) and one optional `talk` (conference). The talk session is always the **active session** while it exists. There is never a third level.

**START TALK** (button in sessions pane, visible when no talk is active):
1. Auto-creates folder `YYYY-MM-DD HH:MM talk` (current date + time, no input needed)
2. Saves main session state to its `session_state.json` immediately
3. Switches mode to `conference`
4. Disconnects all main-session participants with `session_paused` message
5. Loads talk's `session_state.json` if folder already existed (or starts fresh)
6. Writes `daemon_state.json` with `talk` field set

**END TALK** (button in sessions pane, visible when a talk is active):
1. Final write of talk state to its `session_state.json`
2. Disconnects all talk participants with `session_paused` message
3. Restores main session state from main's `session_state.json` into AppState
4. Switches mode back to `workshop`
5. Sets `talk: null` in `daemon_state.json`
6. Main-session participants (retrying every 5s) are now recognized by UUID → reconnect with scores

**Conference mode toggle** (host switches mode dropdown):
- Only creates the talk folder and switches mode (steps 1–3 of START TALK)
- Does NOT disconnect main-session participants
- Does NOT save/restore state
- The mode change only affects how new participants are named (auto-assigned vs custom)

---

## Participant UUID Resolution on WebSocket Connect

Every incoming WebSocket connection carries the participant's UUID (from localStorage). The server resolves it in order:

```
1. UUID in CURRENT active session's participants?
      YES → welcome back; restore name + score

2. UUID in the OTHER session (main while talk active, or talk's known UUIDs after END TALK)?
      YES → send session_paused; close WS; client retries every 5s

3. UUID is a former talk participant (talk ended, UUID not in main session)?
      → treat as unknown; allow join as new participant for main session

4. UUID completely unknown?
      → new participant for current session
```

The `participants` map in `session_state.json` is the authoritative registry of who belongs to which session. After END TALK, talk participants who retry are not in main's participant map → branch 3 → they join the main workshop as new participants (conference attendees are different people from workshop attendees).

### Race condition on server restart

There is a brief window after server restart before the daemon has posted the restore payload to `/api/session/sync`. If a participant reconnects during this window, their UUID is unknown (AppState is empty) → they are admitted as a new participant and their score is temporarily 0. When the daemon posts the restore payload, their score is updated and broadcast. The next WebSocket state push delivers the correct score. This race window is short (daemon polling cycle) and acceptable — the participant sees their score restored within seconds.

### "Session paused" participant experience

When a participant's WS is closed with `session_paused`:
- Client receives: `{ "type": "session_paused", "message": "Session paused — you'll reconnect automatically" }`
- Participant page shows a full-screen overlay with that message (no spinner, no panic)
- Client retries silently every 5s
- When their session is restored (END TALK for main participants, or new session for talk participants), UUID is recognized → overlay disappears → participant is back with score intact

---

## Host UI Changes

### Sessions pane (permanent right panel, not a tab)

```
SESSIONS
────────────────────────────────────────
  Talk:  2026-03-25 12:30 talk   [END TALK]   ← blinking yellow border
  Main:  2026-03-25 WebSecurity   [PAUSE]
────────────────────────────────────────
  [ START TALK ]   ← only shown when no talk is active

  FRAGILE (no folder for today):
  [ 2026-03-25 _________ ]  [ CREATE ]
  ← blinking yellow CREATE button, date pre-filled
```

- **Talk row**: blinking yellow border whenever a talk is active (signals nesting to host)
- **PAUSE / RESUME button** on main session: pauses/resumes transcription. When paused: button blinks yellow, tooltip *"Not recording"*
- **Rename button**: removed entirely
- **END TALK / START TALK**: mutually exclusive single button
- No emojis in any button labels

### Warning banners
- 5:30–6:00pm: yellow blinking banner at top of host panel — *"Recording pauses in 30 min"*
- After 6pm auto-pause: persistent yellow strip — *"Recording paused"* (until host resumes or starts talk)

---

## Restore on Server Restart

1. Daemon detects server is up (via its polling loop)
2. Reads `daemon_state.json` → determines active session(s) per precedence rules
3. Reads `session_state.json` from active session folder
4. Posts restored state to `/api/session/sync` with full payload (see updated contract below)
5. AppState is populated: mode, participants, scores, activity, poll, qa, wordcloud, debate, codereview, leaderboard, token_usage
6. Participants reconnecting with known UUIDs get their scores back

### Updated `/api/session/sync` contract

The daemon POSTs to `/api/session/sync` with a payload that now includes the full session state:

```json
{
  "stack": [...],
  "discussion_points": [...],
  "session_state": { ...full session_state.json content... }
}
```

The server merges `session_state` into AppState when present. The `stack` and `discussion_points` fields remain for backward compatibility.

---

## What Changes

- `transcript_keypoints.md` → `transcript_discussion.md` (rename in daemon and all consumers)
- `daemon_state.json` schema: `{main, talk}` replaces `{session_stack: [...]}`
- New `session_state.json` written per-session folder, every 5s
- `/api/session/sync` extended with `session_state` field
- Host sessions pane: START TALK / END TALK buttons, FRAGILE CREATE flow, no rename button
- Participant WS handler: UUID resolution against session state, `session_paused` message type
- Participant page: `session_paused` overlay
- 5:30pm / 6pm / midnight timing logic (new)

## What Does NOT Change

- Transcript file selection logic (by YYYYMMDD in filename)
- Transcript timestamp appending
- Notes file detection (most recent `.txt` in session folder)
- Session folder date-range matching logic
- Summary / discussion point generation and storage in `transcript_discussion.md`

---

## Out of Scope

- Three-level session nesting
- Participant self-service session switching
- Talk custom naming (always auto-named `YYYY-MM-DD HH:MM talk`)
- Database persistence (remains in-memory + file)
- Configurable timing values (5:30pm warning and 6pm pause are fixed)
