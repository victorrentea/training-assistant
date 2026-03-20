# UUID-Based Participant Identity

## Problem

Participants are currently identified by display name (unique, used as dict key everywhere). This causes:
- No duplicate names allowed (frustrating in large groups)
- Identity lost on name change (disconnect + rejoin required)
- Cannot test with multiple tabs in the same browser (localStorage shared)

## Solution

Replace name-based identity with UUID-based identity. Names become a mutable display attribute.

## Identity Model

### UUID Generation & Storage

- **Client-side:** `crypto.randomUUID()` generates the UUID
- **Host cookie detection:** When `/host` is visited, backend sets `Set-Cookie: is_host=1; Path=/; SameSite=Strict`
- **Storage strategy:**
  - If `is_host` cookie present → UUID in `sessionStorage` (per-tab, for multi-tab testing)
  - If no cookie → UUID in `localStorage` (persistent, survives tab close)
- **Display name:** always in `localStorage` (pre-fill convenience)

Note: No `Secure` flag on the cookie — it must work on `http://localhost` during local development.

### Backend State (state.py)

All dictionaries keyed by UUID instead of name:

```python
participants: dict[str, WebSocket] = {}       # uuid → ws
participant_names: dict[str, str] = {}        # uuid → display_name
locations: dict[str, str] = {}               # uuid → location
votes: dict[str, str] = {}                   # uuid → option_id
scores: dict[str, int] = {}                  # uuid → score
base_scores: dict[str, int] = {}             # uuid → base_score
vote_times: dict[str, datetime] = {}         # uuid → timestamp
```

Q&A questions:
```python
qa_questions[qid]["author"] = uuid            # uuid, not name
qa_questions[qid]["upvoters"] = set[uuid]     # set of uuids
```

`suggested_names` set: **removed** from state. The `/api/suggest-name` endpoint still returns LOTR names but no longer tracks which names have been handed out (uniqueness is irrelevant now).

### WebSocket Protocol

**Connection:** `/ws/{uuid}` (was `/ws/{participant_name}`)

**Host connection:** `/ws/__host__` remains as-is. `__host__` is treated as a reserved UUID value.

**First message (required):** `{"type": "set_name", "name": "John"}`
- Registers the display name for this UUID
- Same message type used for renames mid-session
- **Enforcement:** server ignores all non-`set_name` messages until name is set. Unnamed UUIDs are excluded from participant count and broadcasts.

**Existing message types** (`vote`, `multi_vote`, `location`, `wordcloud_word`) — unchanged in format, but backend uses the UUID from the WS connection path instead of name.

**New WS message types (replacing REST):**
- `{"type": "qa_submit", "text": "My question?"}` — replaces `POST /api/qa/question`
- `{"type": "qa_upvote", "question_id": "abc123"}` — replaces `POST /api/qa/upvote`

**Removed REST endpoints:**
- `POST /api/qa/question` (body had `name` field)
- `POST /api/qa/upvote` (body had `name` field)

### Broadcast Messages (server → clients)

Since duplicate names are allowed, name-keyed dicts would cause collisions. Different broadcast strategies for participants vs host:

#### Participant broadcast (per-connection personalized)

Each participant receives a state message with:
- `participant_count` → integer
- `my_score` → their own score (resolved server-side from their UUID)
- `qa_questions[]` → each question includes:
  - `author` → display name (resolved)
  - `is_own` → boolean (true if this participant authored it, computed server-side)
  - `has_upvoted` → boolean (true if this participant upvoted, computed server-side)
  - Other fields unchanged (`id`, `text`, `upvote_count`, `answered`, `timestamp`)

#### Host broadcast

Host receives richer data as a list of participant objects (collision-safe):
- `participants` → `[{uuid, name, score, location}, ...]`
- `qa_questions[]` → same as now but `author` resolved to display name

This replaces the old `participant_names` (list), `participant_locations` (name-keyed dict), and `scores` (name-keyed dict) with a single unified list.

## Inline Name Editing (Participant UI)

- Display name shown in top bar with pencil icon (✏️)
- Click → name becomes editable input with green checkmark (✓) to confirm
- On confirm: sends `{"type": "set_name", "name": "NewName"}` via WS
- Backend updates `participant_names[uuid]`, broadcasts to all
- `localStorage` updated with new name
- **Duplicate names allowed** — no uniqueness check, no warning

## Removed Features

- **Disconnect button (☢️):** removed — no longer conceptually needed
- **Name uniqueness check:** removed entirely (backend + frontend)
- **`suggested_names` set:** removed from state entirely

## Host Cookie

- **Set by:** `/host` endpoint response
- **Cookie:** `is_host=1; Path=/; SameSite=Strict` (no `Secure` flag — must work on localhost)
- **Effect:** participant.js checks for this cookie to decide UUID storage location
- **Real participants** never visit `/host`, so never get the cookie

## Vote Persistence Note

Client-side vote restoration from `localStorage` is per-browser. Server-side vote tracking is per-UUID. For host testing tabs (`sessionStorage` UUID), votes are intentionally not shared across tabs — each tab is an independent test participant.

## Backward Compatibility

No migration needed. Server restart clears all in-memory state. Old `localStorage` keys (`workshop_participant_name`) are reused for display name pre-fill. New key (`workshop_participant_uuid`) added for UUID. Deploy is atomic via Railway auto-deploy.

## Files Affected

### Backend
- `state.py` — all dicts keyed by UUID, add `participant_names` dict, remove `suggested_names`
- `routers/ws.py` — route `/ws/{uuid}`, handle `set_name` (with enforcement), `qa_submit`, `qa_upvote` messages, remove name-taken logic
- `routers/qa.py` — remove `POST /api/qa/question` and `POST /api/qa/upvote` REST endpoints
- `routers/poll.py` — update score calculation to use UUID keys, send per-connection `my_score`
- `messaging.py` — build per-participant personalized messages, build host participant list
- `main.py` — set host cookie on `/host` endpoint

### Frontend
- `static/participant.js` — UUID generation/storage, WS connect with UUID, `set_name` message, inline name editing, Q&A via WS, use `my_score`/`my_uuid`/`is_own`, remove disconnect button, remove duplicate name check
- `static/host.js` — consume new `participants` list format instead of separate name/location/score dicts
- `static/participant.html` — inline name edit UI (pencil + input), remove disconnect button

### Tests
- `test_main.py` — update all WS connections to use UUIDs, send `set_name`, update assertions for new message format
- `test_e2e.py` — update WebSocket URLs and message flows
