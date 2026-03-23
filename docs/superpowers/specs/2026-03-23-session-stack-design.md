# Session Stack & Progressive Summarization

**Date:** 2026-03-23
**Status:** Draft

## Problem

The tool currently has a flat session model — one implicit session per daemon run. This doesn't support:
- Multi-day workshops resuming across days/weeks
- Nested sessions (e.g., a lunch-break talk inside a workshop day)
- Persistent key points that survive daemon restarts and accumulate over time
- Transcript isolation between independent sessions happening on the same day

## Design

### Session Model

A **session** is identified by a folder name in the sessions directory. The folder is the canonical persistence layer:

```
sessions/
  2026-03-23 WebSecurity@itkonect/
    web security@itkonect.txt    ← trainer's handwritten notes (optional)
    key_points.json              ← accumulated key points (written by daemon)
  2026-03-25 Lunch Talk/
    key_points.json              ← ad-hoc session, no prepared notes
```

Every session MUST have a folder. If one doesn't exist when starting a session, the daemon creates it.

**Session data:**
```python
@dataclass
class Session:
    name: str                     # = folder name
    folder_path: Path             # resolved absolute path
    started_at: datetime          # when this session window opened
    ended_at: datetime | None     # set when session is ended (None = active)
    summary_watermark: int        # transcript line offset of last summarization
```

`key_points.json` replaces the existing `summary_cache.json`. Format:
```json
{
  "points": [
    {"text": "...", "source": "discussion", "time": "14:30"},
    {"text": "...", "source": "notes"}
  ]
}
```

### System Boundaries — Who Owns What

The **daemon** owns session state. This matches the existing architecture where the daemon has local disk access and the server (Railway) has ephemeral storage.

- **Daemon**: owns session stack, persists to `sessions/daemon_state.json`, creates folders, reads/writes `key_points.json`, manages transcript windowing
- **Server (AppState)**: mirrors session state for WebSocket broadcast to clients. Does not persist sessions — receives them from the daemon.
- **Host UI**: sends session commands to server as pending requests. Daemon picks them up via long-polling (same pattern as `quiz_request`, `debate_ai_request`).

**Request flow pattern** (matches existing architecture):
1. Host clicks "Start New Session" → `POST /api/session/start {name}` → server stores in `state.session_request`
2. Daemon polls `GET /api/session/request` → picks up pending request, clears flag
3. Daemon pushes new session, creates folder, loads key points
4. Daemon syncs stack to server via `POST /api/session/sync` → server updates AppState, broadcasts

### Session Stack

Sessions are managed as a stack (max depth 3, enforced by disabling "Start New Session" button at depth 3):

- **Push**: "Start New Session" creates a new session, pushes onto stack
- **Pop**: "End Session" sets `ended_at` on current, pops stack, restores parent
- **Top of stack** = the currently active session

The stack is persisted to `sessions/daemon_state.json`:
```json
{
  "stack": [
    {"name": "2026-03-23 WebSecurity@itkonect", "started_at": "2026-03-23T09:00:00", "ended_at": null, "summary_watermark": 450},
    {"name": "Lunch Talk", "started_at": "2026-03-23T12:00:00", "ended_at": null, "summary_watermark": 0}
  ]
}
```

### Startup & Recovery

**Fresh startup (no `daemon_state.json`):**
1. Scan session folders for one containing today's date
2. If found → auto-start that session (push onto empty stack), load `key_points.json`
3. If not found → "no active session" state
4. If multiple folders match today's date → pick the one with the latest alphabetical sort (existing behavior)

**Restart with existing `daemon_state.json`:**
1. Load stack from file
2. For each session in stack, load `key_points.json` from its folder
3. Sync full state to server
4. Resume normal operation

### Host UI — Session Panel

Located in the right pane below the participant list (bottom third):

- **Current session name** — displayed as editable label (pencil icon for rename)
- **"Start New Session"** button → prompt with:
  - Dropdown/suggestions from existing session folders
  - Pre-filled with today's date (e.g., `2026-03-23`)
  - Host can type any name
  - If no matching folder exists, one is created automatically
  - Disabled when stack depth = 3
- **"End Session"** button — only visible when stack depth > 1; pops current session
- **Breadcrumb** — shows stack visually: `Workshop > Lunch Talk` (read-only, subtle)

### Transcript Time-Windowing

Each session's valid transcript is its time range **minus nested session holes**:

```
Workshop:    09:00 ═══════════════════════════ 17:00
Lunch talk:              12:00 ════ 13:00

Workshop transcript  = [09:00–12:00] + [13:00–17:00]
Lunch talk transcript = [12:00–13:00]
```

Implementation: when extracting transcript for the current session, the daemon:
1. Collects all transcript lines with full datetime timestamps in `[session.started_at, now]`
2. Excludes lines falling within any ended nested session's `[started_at, ended_at]`
3. For multi-day sessions, includes lines from previous days that fall within a session window of the same name

**Midnight crossing:** Transcript lines now have full datetime stamps (`[YYYY-MM-DD HH:MM:SS]`), so windowing works correctly across midnight boundaries. The `Session.started_at` is a full `datetime`, not just a time.

**Notes resolution:** Uses existing `find_session_folder` heuristic — picks the `.txt` file in the folder. If no `.txt` file exists, no notes are shown.

### Progressive Summary Generation

Triggered **on-demand only** — host or participant clicks the brain icon.

**Flow:**
1. Daemon computes **delta transcript**: text from `summary_watermark` to current end of transcript, filtered to current session's valid time windows
2. Sends to LLM: delta transcript + **last 5 existing key points** as context
3. LLM responds with:
   - **Updated points**: modifications to existing points (e.g., merging new discussion into an old point). Identified by index.
   - **New points**: entirely new takeaways
4. Points list is patched in-place (silent replacement for updates)
5. `summary_watermark` is advanced to current transcript position
6. `key_points.json` is written to the session folder
7. `daemon_state.json` is updated with new watermark
8. Updated points are POSTed to server → broadcast to all clients

**LLM response format:**
```json
{
  "updated": [{"index": 2, "text": "revised point", "source": "discussion", "time": "14:30"}],
  "new": [{"text": "new takeaway", "source": "discussion", "time": "15:10"}]
}
```

### Multi-Day Continuity

When a session is started with a folder name that already has `key_points.json`:
- Previous key points are loaded and displayed immediately
- New brain-icon clicks add to / update the existing points
- No re-summarization of old transcript needed — the points ARE the summary

### Renaming a Session

Host can rename via pencil icon. If the new name matches an existing folder:
- Notes and key points are re-resolved from that folder
- If renaming away from an old folder, key points remain in the old folder (not deleted)

If the new name has no matching folder, one is created.

### Edge Cases

- **Folder deleted while session active**: daemon logs warning, summary writes fail silently, session continues
- **Multiple folders matching today's date**: pick latest alphabetical sort (existing `find_session_folder` behavior)
- **Stack overflow (depth > 3)**: UI disables "Start New Session" button at depth 3

## Sequence Diagram

```
Host                    Server (AppState)           Daemon                  LLM (Claude)
 │                           │                        │                        │
 ├─ STARTUP ─────────────────┤────────────────────────┤                        │
 │                           │                        │                        │
 │                           │                        │  scan folders locally   │
 │                           │                        │  load daemon_state.json │
 │                           │                        │  load key_points.json   │
 │                           │                        │                        │
 │                           │  POST /api/session/sync │                        │
 │                           │<───────────────────────│                        │
 │                           │  (stack + key points)   │                        │
 │  WS: session_stack +      │                        │                        │
 │  key_points broadcast     │                        │                        │
 │<──────────────────────────│                        │                        │
 │                           │                        │                        │
 ├─ BRAIN ICON CLICK ────────┤────────────────────────┤                        │
 │                           │                        │                        │
 │  Click 🧠                  │                        │                        │
 │──────────────────────────>│                        │                        │
 │                           │  set force_requested    │                        │
 │                           │                        │                        │
 │                           │  GET /api/summary/force │                        │
 │                           │<───────────────────────│  (daemon polls)        │
 │                           │  {requested: true}      │                        │
 │                           │───────────────────────>│                        │
 │                           │                        │                        │
 │                           │                        │  compute delta          │
 │                           │                        │  (watermark → now,      │
 │                           │                        │   session time windows) │
 │                           │                        │                        │
 │                           │                        │  delta + last 5 points  │
 │                           │                        │───────────────────────>│
 │                           │                        │  {updated, new}         │
 │                           │                        │<───────────────────────│
 │                           │                        │                        │
 │                           │                        │  patch points in-place  │
 │                           │                        │  write key_points.json  │
 │                           │                        │  update watermark       │
 │                           │                        │                        │
 │                           │  POST /api/summary      │                        │
 │                           │<───────────────────────│                        │
 │  WS: updated key points   │                        │                        │
 │<──────────────────────────│                        │                        │
 │                           │                        │                        │
 ├─ START NEW SESSION ───────┤────────────────────────┤                        │
 │                           │                        │                        │
 │  Click "Start New Session"│                        │                        │
 │  → prompt with folder     │                        │                        │
 │    suggestions + date     │                        │                        │
 │──────────────────────────>│                        │                        │
 │                           │  store session_request  │                        │
 │                           │  {action: "start",      │                        │
 │                           │   name: "Lunch Talk"}   │                        │
 │                           │                        │                        │
 │                           │  GET /api/session/request│                        │
 │                           │<───────────────────────│  (daemon polls)        │
 │                           │  {action: "start", ...} │                        │
 │                           │───────────────────────>│                        │
 │                           │                        │                        │
 │                           │                        │  create folder if needed│
 │                           │                        │  push session onto stack│
 │                           │                        │  load key_points.json   │
 │                           │                        │  save daemon_state.json │
 │                           │                        │                        │
 │                           │  POST /api/session/sync │                        │
 │                           │<───────────────────────│                        │
 │  WS: new session_stack    │                        │                        │
 │  + new key points         │                        │                        │
 │<──────────────────────────│                        │                        │
 │                           │                        │                        │
 ├─ END SESSION ─────────────┤────────────────────────┤                        │
 │                           │                        │                        │
 │  Click "End Session"      │                        │                        │
 │──────────────────────────>│                        │                        │
 │                           │  store session_request  │                        │
 │                           │  {action: "end"}        │                        │
 │                           │                        │                        │
 │                           │  GET /api/session/request│                        │
 │                           │<───────────────────────│  (daemon polls)        │
 │                           │───────────────────────>│                        │
 │                           │                        │                        │
 │                           │                        │  set ended_at on current│
 │                           │                        │  pop stack              │
 │                           │                        │  load parent's points   │
 │                           │                        │  save daemon_state.json │
 │                           │                        │                        │
 │                           │  POST /api/session/sync │                        │
 │                           │<───────────────────────│                        │
 │  WS: restored stack       │                        │                        │
 │  + parent key points      │                        │                        │
 │<──────────────────────────│                        │                        │
```

## Changes Required

### Backend (`state.py`)
- Add `session_stack: list[dict]` to AppState (mirrors daemon's stack for broadcast)
- Add `session_request: dict | None` for pending host commands
- Add session-related fields to WebSocket broadcast
- Remove `summary_force_full_day` (superseded by session-aware summarization)

### New router (`routers/session.py`)
- `POST /api/session/start` — store pending start request (host-only)
- `POST /api/session/end` — store pending end request (host-only)
- `PATCH /api/session/rename` — store pending rename request (host-only)
- `GET /api/session/request` — daemon polls for pending commands, clears flag (host-only)
- `POST /api/session/sync` — daemon pushes current stack + key points (host-only)
- `GET /api/session/folders` — list available session folders for UI suggestions (host-only)

### Daemon (`training_daemon.py`)
- Session stack management (push/pop/rename)
- Persist stack to `sessions/daemon_state.json`
- Folder creation for new sessions
- Transcript time-windowing with nested session hole exclusion
- Per-session `key_points.json` read/write
- Per-session `summary_watermark` tracking
- Auto-detection of today's session folder on startup
- Poll `GET /api/session/request` in main loop

### Summarizer (`daemon/summarizer.py`)
- New LLM response format: `{updated, new}` instead of flat array
- Accept last 5 points as context parameter
- Point patching logic (in-place replacement for updates)

### Host UI (`static/host.js` + `host.html`)
- Session management panel (bottom-right, below participant list)
- Start/End/Rename session controls
- Breadcrumb display
- Session folder suggestions dropdown
- Brain icon behavior scoped to current session
- Key points display switches when session changes
- "Start New Session" disabled at stack depth 3

### Migration
- Remove `summary_cache.json` usage — replaced by per-session `key_points.json`
- Remove two-tier locked/draft point model — replaced by flat list with watermark-based delta
