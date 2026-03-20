# UUID-Based Participant Identity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace name-based participant identity with UUID-based identity, allowing duplicate names, inline name editing, and per-tab testing via host cookie.

**Architecture:** All backend state dictionaries switch from name-keyed to UUID-keyed. A new `participant_names` dict maps UUID→display_name. WebSocket path changes from `/ws/{name}` to `/ws/{uuid}`. Q&A submit/upvote migrate from REST to WebSocket messages. Broadcast messages are personalized per-connection (participant gets `my_score`, `is_own`, `has_upvoted`; host gets a list of participant objects). Host page sets a cookie that makes participant.js use `sessionStorage` for UUID (per-tab identity for testing).

**Tech Stack:** Python/FastAPI, vanilla JavaScript, WebSockets

**Spec:** `docs/superpowers/specs/2026-03-20-uuid-participant-identity-design.md`

---

### Task 1: Backend state model — switch all dicts to UUID keys

**Files:**
- Modify: `state.py:23-59`

- [ ] **Step 1: Write failing test — state uses UUID keys**

In `test_main.py`, add a test that connects via `/ws/{uuid}`, sends `set_name`, and verifies the participant appears in state:

```python
# At the top of test_main.py, add:
import uuid as uuid_mod

class TestUUIDIdentity:

    def test_participant_connects_with_uuid_and_sets_name(self, session):
        uid = str(uuid_mod.uuid4())
        with session._client.websocket_connect(f"/ws/{uid}") as ws:
            ws.send_text(json.dumps({"type": "set_name", "name": "Alice"}))
            # Should receive initial state
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "state"
            # Participant should be tracked by UUID
            assert uid in state.participants
            assert state.participant_names.get(uid) == "Alice"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest test_main.py::TestUUIDIdentity::test_participant_connects_with_uuid_and_sets_name -v`
Expected: FAIL — route `/ws/{uuid}` doesn't exist yet, `state.participant_names` doesn't exist.

- [ ] **Step 3: Update state.py**

```python
# In AppState.reset(), change:
# Remove: self.suggested_names: set[str] = set()
# Add: self.participant_names: dict[str, str] = {}  # uuid → display_name
# All other dicts stay the same type signature but are now keyed by UUID (semantic change, no code change needed in state.py)
```

Also update `suggest_name()` — remove `suggested_names` tracking:

```python
def suggest_name(self) -> str:
    taken = set(self.participant_names.values())
    available = [n for n in LOTR_NAMES if n not in taken]
    return available[0] if available else f"Guest{random.randint(100, 999)}"
```

- [ ] **Step 4: Commit state.py changes**

```bash
git add state.py
git commit -m "refactor: switch AppState to UUID-keyed dicts, add participant_names mapping"
```

---

### Task 2: WebSocket handler — UUID path + set_name message

**Files:**
- Modify: `routers/ws.py:1-120`
- Modify: `messaging.py:1-69`

- [ ] **Step 1: Rewrite ws.py websocket_endpoint**

Change the route from `/ws/{participant_name}` to `/ws/{participant_id}`. Handle `set_name` as first required message. Ignore non-`set_name` messages until name is set. Move Q&A handling here (tasks 3-4 will handle that — for now just handle existing message types with UUID).

```python
@router.websocket("/ws/{participant_id}")
async def websocket_endpoint(websocket: WebSocket, participant_id: str):
    pid = participant_id.strip()[:64]
    if not pid:
        await websocket.close(code=1008)
        return

    # Host takeover logic (unchanged, __host__ is a reserved ID)
    if pid == "__host__" and "__host__" in state.participants:
        old_ws = state.participants["__host__"]
        try:
            await old_ws.send_text(json.dumps({"type": "kicked"}))
            await old_ws.close(code=1001)
        except Exception:
            pass
        del state.participants["__host__"]

    await websocket.accept()
    state.participants[pid] = websocket
    named = pid == "__host__"  # host is always "named"
    logger.info(f"Connected: {pid} ({len(state.participants)} total)")

    if pid == "__host__":
        state.participant_names["__host__"] = "Host"
        await send_state_to_host(websocket)
    # Don't send state until named (for participants)

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type")

            if msg_type == "set_name":
                name = str(data.get("name", "")).strip()[:32]
                if name:
                    state.participant_names[pid] = name
                    if not named:
                        named = True
                        await send_state_to_participant(websocket, pid)
                    await broadcast_participant_update()
                continue

            # Ignore all messages until named (except host)
            if not named:
                continue

            if msg_type == "location":
                loc = str(data.get("location", "")).strip()[:80]
                if loc:
                    state.locations[pid] = loc
                    await broadcast_participant_update()

            elif msg_type == "vote":
                option_id = data.get("option_id")
                valid_ids = [o["id"] for o in state.poll["options"]] if state.poll else []
                if state.poll_active and state.poll and not state.poll.get("multi") and option_id in valid_ids:
                    state.votes[pid] = option_id
                    if pid not in state.vote_times:
                        state.vote_times[pid] = datetime.now(timezone.utc)
                    await broadcast({
                        "type": "vote_update",
                        "vote_counts": state.vote_counts(),
                        "total_votes": len(state.votes),
                    })

            elif msg_type == "multi_vote":
                option_ids = data.get("option_ids", [])
                valid_ids = [o["id"] for o in state.poll["options"]] if state.poll else []
                correct_count = state.poll.get("correct_count") if state.poll else None
                max_allowed = correct_count if correct_count else len(valid_ids)
                if (
                    state.poll_active
                    and state.poll
                    and state.poll.get("multi")
                    and isinstance(option_ids, list)
                    and len(option_ids) <= max_allowed
                    and len(set(option_ids)) == len(option_ids)
                    and all(oid in valid_ids for oid in option_ids)
                ):
                    state.votes[pid] = option_ids
                    if pid not in state.vote_times:
                        state.vote_times[pid] = datetime.now(timezone.utc)
                    await broadcast({
                        "type": "vote_update",
                        "vote_counts": state.vote_counts(),
                        "total_votes": len(state.votes),
                    })

            elif msg_type == "wordcloud_word":
                word = str(data.get("word", "")).strip().lower()
                if state.current_activity == ActivityType.WORDCLOUD and word:
                    state.wordcloud_words[word] = state.wordcloud_words.get(word, 0) + 1
                    if pid != "__host__":
                        state.scores[pid] = state.scores.get(pid, 0) + 200
                    await broadcast_state()

            elif msg_type == "qa_submit":
                text = str(data.get("text", "")).strip()
                if text and len(text) <= 280:
                    qid = str(uuid_mod.uuid4())
                    state.qa_questions[qid] = {
                        "id": qid,
                        "text": text,
                        "author": pid,  # UUID, not name
                        "upvoters": set(),
                        "answered": False,
                        "timestamp": time.time(),
                    }
                    state.scores[pid] = state.scores.get(pid, 0) + 100
                    await broadcast_state()

            elif msg_type == "qa_upvote":
                question_id = data.get("question_id")
                q = state.qa_questions.get(question_id)
                if q and q["author"] != pid and pid not in q["upvoters"]:
                    q["upvoters"].add(pid)
                    author_pid = q["author"]
                    state.scores[author_pid] = state.scores.get(author_pid, 0) + 50
                    state.scores[pid] = state.scores.get(pid, 0) + 25
                    await broadcast_state()

    except WebSocketDisconnect:
        state.participants.pop(pid, None)
        state.locations.pop(pid, None)
        state.vote_times.pop(pid, None)
        # Keep participant_names[pid] — they may reconnect
        # Keep scores[pid] and votes[pid] — those persist for the session
        logger.info(f"Disconnected: {pid} ({len(state.participants)} remaining)")
        await broadcast_participant_update()
```

Note: `import uuid as uuid_mod` and `import time` at the top. Import new messaging functions.

- [ ] **Step 2: Update messaging.py**

Replace `build_state_message()` and `send_state_to()` with per-audience functions:

```python
import json
import uuid as uuid_mod
from typing import Optional
from datetime import datetime, timezone
from fastapi import WebSocket

from backend_version import get_backend_version
from state import state


def participant_ids() -> list[str]:
    """Return sorted list of participant UUIDs (excluding __host__ and unnamed)."""
    return sorted(
        pid for pid in state.participants
        if pid != "__host__" and pid in state.participant_names
    )


def _base_state() -> dict:
    """Fields common to both host and participant state messages."""
    now = datetime.now(timezone.utc)
    last_seen = state.daemon_last_seen
    daemon_connected = last_seen is not None and (now - last_seen).total_seconds() < 5
    return {
        "type": "state",
        "backend_version": get_backend_version(),
        "poll": state.poll,
        "poll_active": state.poll_active,
        "vote_counts": state.vote_counts(),
        "participant_count": len(participant_ids()),
        "current_activity": state.current_activity,
        "wordcloud_words": state.wordcloud_words,
        "wordcloud_topic": state.wordcloud_topic,
    }


def _build_qa_for_participant(pid: str) -> list[dict]:
    return [
        {
            "id": qid,
            "text": q["text"],
            "author": state.participant_names.get(q["author"], "Unknown"),
            "is_own": q["author"] == pid,
            "has_upvoted": pid in q["upvoters"],
            "upvote_count": len(q["upvoters"]),
            "answered": q["answered"],
            "timestamp": q["timestamp"],
        }
        for qid, q in sorted(
            state.qa_questions.items(),
            key=lambda item: (-len(item[1]["upvoters"]), item[1]["timestamp"])
        )
    ]


def _build_qa_for_host() -> list[dict]:
    return [
        {
            "id": qid,
            "text": q["text"],
            "author": state.participant_names.get(q["author"], "Unknown"),
            "upvote_count": len(q["upvoters"]),
            "answered": q["answered"],
            "timestamp": q["timestamp"],
        }
        for qid, q in sorted(
            state.qa_questions.items(),
            key=lambda item: (-len(item[1]["upvoters"]), item[1]["timestamp"])
        )
    ]


def build_participant_state(pid: str) -> dict:
    msg = _base_state()
    msg["my_score"] = state.scores.get(pid, 0)
    msg["qa_questions"] = _build_qa_for_participant(pid)
    return msg


def build_host_state() -> dict:
    msg = _base_state()
    now = datetime.now(timezone.utc)
    last_seen = state.daemon_last_seen
    daemon_connected = last_seen is not None and (now - last_seen).total_seconds() < 5
    msg["daemon_last_seen"] = last_seen.isoformat() if last_seen else None
    msg["daemon_connected"] = daemon_connected
    msg["daemon_session_folder"] = state.daemon_session_folder
    msg["daemon_session_notes"] = state.daemon_session_notes
    msg["quiz_preview"] = state.quiz_preview
    msg["scores"] = {state.participant_names.get(pid, pid): pts for pid, pts in state.scores.items()}
    msg["participants"] = [
        {
            "uuid": pid,
            "name": state.participant_names.get(pid, pid),
            "score": state.scores.get(pid, 0),
            "location": state.locations.get(pid, ""),
        }
        for pid in participant_ids()
    ]
    msg["participant_count"] = len(msg["participants"])
    msg["participant_names"] = [p["name"] for p in msg["participants"]]
    msg["participant_locations"] = {p["name"]: p["location"] for p in msg["participants"]}
    msg["qa_questions"] = _build_qa_for_host()
    return msg


# Keep backward-compat name for quiz router etc. that just need a basic broadcast
def build_state_message() -> dict:
    """Fallback: build host state (used by non-WS code paths like REST endpoints)."""
    return build_host_state()


async def broadcast_state():
    """Send personalized state to each connected client."""
    dead = []
    for pid, ws in state.participants.items():
        try:
            if pid == "__host__":
                await ws.send_text(json.dumps(build_host_state()))
            elif pid in state.participant_names:
                await ws.send_text(json.dumps(build_participant_state(pid)))
        except Exception:
            dead.append(pid)
    for pid in dead:
        state.participants.pop(pid, None)


async def broadcast(message: dict, exclude: Optional[str] = None):
    """Send identical message to all connected clients (for non-personalized messages like vote_update)."""
    dead = []
    for pid, ws in state.participants.items():
        if pid == exclude:
            continue
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.append(pid)
    for pid in dead:
        state.participants.pop(pid, None)


async def broadcast_participant_update():
    """Broadcast participant count/list update (personalized for host vs participants)."""
    pids = participant_ids()
    count = len(pids)
    # Participants get a simple count
    pax_msg = {"type": "participant_count", "count": count}
    # Host gets full details
    host_msg = {
        "type": "participant_count",
        "count": count,
        "names": [state.participant_names.get(pid, pid) for pid in pids],
        "locations": {state.participant_names.get(pid, pid): state.locations.get(pid, "") for pid in pids},
        "participants": [
            {
                "uuid": pid,
                "name": state.participant_names.get(pid, pid),
                "score": state.scores.get(pid, 0),
                "location": state.locations.get(pid, ""),
            }
            for pid in pids
        ],
    }
    dead = []
    for pid, ws in state.participants.items():
        try:
            msg = host_msg if pid == "__host__" else pax_msg
            await ws.send_text(json.dumps(msg))
        except Exception:
            dead.append(pid)
    for pid in dead:
        state.participants.pop(pid, None)


async def send_state_to_participant(ws: WebSocket, pid: str):
    await ws.send_text(json.dumps(build_participant_state(pid)))


async def send_state_to_host(ws: WebSocket):
    await ws.send_text(json.dumps(build_host_state()))


# Legacy: used by some REST endpoints that broadcast after mutation
async def send_state_to(ws: WebSocket):
    """Deprecated — sends host state. Use send_state_to_participant or send_state_to_host."""
    await ws.send_text(json.dumps(build_host_state()))
```

- [ ] **Step 3: Run test to verify it passes**

Run: `python3 -m pytest test_main.py::TestUUIDIdentity::test_participant_connects_with_uuid_and_sets_name -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add routers/ws.py messaging.py
git commit -m "feat: UUID-based WebSocket routing with set_name protocol and personalized broadcasts"
```

---

### Task 3: Remove Q&A REST endpoints, host submits Q&A with name "Host"

**Files:**
- Modify: `routers/qa.py` — remove `POST /api/qa/question` and `POST /api/qa/upvote`
- Modify: `routers/ws.py` — Q&A handlers already added in Task 2
- Modify: `static/host.js:952-963` — host Q&A submit now goes through WS

- [ ] **Step 1: Remove REST Q&A submit and upvote endpoints from qa.py**

Remove the `POST /api/qa/question` endpoint (lines 34-57) and `POST /api/qa/upvote` endpoint (lines 60-78). Remove `QuestionSubmit` and `QuestionUpvote` models. Keep `QuestionEdit`, `AnswerToggle`, and host-only endpoints (PATCH, DELETE, answer, clear).

- [ ] **Step 2: Update host.js — hostSubmitQA() via WebSocket**

Change `hostSubmitQA()` to send via WS instead of REST:

```javascript
async function hostSubmitQA() {
    const input = document.getElementById('host-qa-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text || !ws) return;
    ws.send(JSON.stringify({ type: 'qa_submit', text }));
    input.value = '';
    input.focus();
}
```

- [ ] **Step 3: Update qa.py broadcast calls**

The remaining host-only endpoints (edit, delete, answer, clear) call `broadcast(build_state_message())`. Since `build_state_message()` now returns host state, and these are REST endpoints (not per-connection), change them to use `broadcast_state()`:

```python
from messaging import broadcast_state
# Replace all: await broadcast(build_state_message())
# With: await broadcast_state()
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest test_main.py -v`
Expected: Q&A tests will fail (they use the old REST endpoints). Fix them in Task 6.

- [ ] **Step 5: Commit**

```bash
git add routers/qa.py static/host.js
git commit -m "feat: migrate Q&A submit/upvote from REST to WebSocket, remove old endpoints"
```

---

### Task 4: Update poll.py scoring to use UUID keys

**Files:**
- Modify: `routers/poll.py:88-166`

- [ ] **Step 1: Update score broadcasting in poll.py**

In `set_correct_options()`:
- The scoring loop already iterates `state.votes.items()` which are now UUID-keyed — this just works.
- Change the `scores` broadcast (line 150) to use `broadcast_state()` instead of the raw scores dict.
- Change the per-participant result sending (lines 152-164) to use UUID iteration.

```python
# Line 150: Replace
await broadcast({"type": "scores", "scores": state.scores})
# With:
await broadcast_state()

# Lines 152-164: Keep but iterate by UUID
for pid, ws in list(state.participants.items()):
    if pid == "__host__":
        continue
    selection = state.votes.get(pid)
    if selection is None:
        continue
    voted = set(selection) if isinstance(selection, list) else {selection}
    await ws.send_text(json.dumps({
        "type": "result",
        "correct_ids": list(correct_set),
        "voted_ids": list(voted),
        "score": state.scores.get(pid, 0),
    }))
```

- [ ] **Step 2: Update other poll.py endpoints that broadcast**

`create_poll()`, `set_poll_status()`, `clear_poll()` all call `broadcast(build_state_message())`. Change to `broadcast_state()`.

- [ ] **Step 3: Update suggest_name endpoint**

The `suggest_name()` in state.py was already updated in Task 1 to not use `suggested_names`. No changes needed in poll.py.

- [ ] **Step 4: Commit**

```bash
git add routers/poll.py
git commit -m "feat: update poll scoring to work with UUID-keyed state"
```

---

### Task 5: Host cookie + pages.py

**Files:**
- Modify: `routers/pages.py:15-17`

- [ ] **Step 1: Set cookie on /host response**

```python
from fastapi.responses import HTMLResponse, FileResponse, Response

@router.get("/host", response_class=HTMLResponse, dependencies=[Depends(require_host_auth)])
async def host_page():
    response = FileResponse("static/host.html")
    response.set_cookie("is_host", "1", path="/", samesite="strict")
    return response
```

- [ ] **Step 2: Commit**

```bash
git add routers/pages.py
git commit -m "feat: set is_host cookie when serving /host page"
```

---

### Task 6: Frontend participant.js — UUID, set_name, inline editing, WS Q&A

**Files:**
- Modify: `static/participant.js:1-920`
- Modify: `static/participant.html:27-41`

This is the largest frontend change. Key modifications:

- [ ] **Step 1: Add UUID generation and storage logic at the top of participant.js**

```javascript
// Replace the first few lines with:
const LS_KEY = 'workshop_participant_name';
const LS_UUID_KEY = 'workshop_participant_uuid';
const LS_VOTE_KEY = 'workshop_vote';

const isHost = document.cookie.includes('is_host=1');
const uuidStorage = isHost ? sessionStorage : localStorage;

function getOrCreateUUID() {
    let uid = uuidStorage.getItem(LS_UUID_KEY);
    if (!uid) {
        uid = crypto.randomUUID();
        uuidStorage.setItem(LS_UUID_KEY, uid);
    }
    return uid;
}

let myUUID = getOrCreateUUID();
let ws = null;
let myName = '';
// ... rest of existing variables unchanged
```

- [ ] **Step 2: Update connectWS() to use UUID path and send set_name**

```javascript
function connectWS(name) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${location.host}/ws/${encodeURIComponent(myUUID)}`;
    ws = new WebSocket(url);

    ws.onopen = () => {
        document.getElementById('join-screen').style.display = 'none';
        document.getElementById('main-screen').style.display = 'block';
        document.getElementById('display-name').textContent = myName;

        // Send name as first message
        ws.send(JSON.stringify({ type: 'set_name', name: myName }));

        // Send stored GPS location if available, otherwise silent timezone fallback
        const storedLocation = localStorage.getItem(LS_LOCATION_KEY);
        sendLocation(storedLocation || getTimezoneLocation());
        updateLocationPrompt();
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleMessage(msg);
    };

    ws.onclose = () => {
        setTimeout(() => connectWS(myName), 3000);
    };
}
```

Remove: `_nameTaken` logic, `handleNameTaken()` function, `name_taken` message handling.

- [ ] **Step 3: Update join() — remove name uniqueness concerns**

```javascript
function join() {
    const input = document.getElementById('name-input');
    const name = input.value.trim() || suggestedName;
    if (!name) { input.focus(); return; }
    _joinedWithSuggestion = !input.value.trim();
    myName = name;
    localStorage.setItem(LS_KEY, name);
    connectWS(name);
}
```

- [ ] **Step 4: Remove disconnect button, add inline name editing**

In participant.html, replace the leave button with inline edit UI:

```html
<span class="status-left">
    <span class="mic-icon">🎙</span>
    <span><span class="dot"></span>
        <strong id="display-name"></strong>
        <button id="edit-name-btn" class="edit-name-btn" title="Change name">✏️</button>
        <span id="name-edit-wrap" style="display:none;">
            <input id="name-edit-input" type="text" maxlength="32" />
            <button id="name-edit-ok" class="edit-name-ok" title="Confirm">✓</button>
        </span>
    </span>
    <span id="my-score" style="display:none; color:var(--accent2); font-weight:700; font-size:.85rem;"></span>
</span>
```

Remove the leave button from HTML.

In participant.js, remove the leave-btn event listener (lines 128-150). Add:

```javascript
document.getElementById('edit-name-btn').addEventListener('click', () => {
    const display = document.getElementById('display-name');
    const editWrap = document.getElementById('name-edit-wrap');
    const editInput = document.getElementById('name-edit-input');
    const editBtn = document.getElementById('edit-name-btn');
    editInput.value = myName;
    display.style.display = 'none';
    editBtn.style.display = 'none';
    editWrap.style.display = '';
    editInput.focus();
    editInput.select();
});

function confirmNameEdit() {
    const newName = document.getElementById('name-edit-input').value.trim();
    if (newName && newName !== myName) {
        myName = newName;
        localStorage.setItem(LS_KEY, myName);
        document.getElementById('display-name').textContent = myName;
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'set_name', name: myName }));
        }
    }
    document.getElementById('display-name').style.display = '';
    document.getElementById('edit-name-btn').style.display = '';
    document.getElementById('name-edit-wrap').style.display = 'none';
}

document.getElementById('name-edit-ok').addEventListener('click', confirmNameEdit);
document.getElementById('name-edit-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') confirmNameEdit();
    if (e.key === 'Escape') {
        document.getElementById('display-name').style.display = '';
        document.getElementById('edit-name-btn').style.display = '';
        document.getElementById('name-edit-wrap').style.display = 'none';
    }
});
```

- [ ] **Step 5: Update handleMessage for new state format**

```javascript
// In case 'state':
updateScore(msg.my_score);
window._myScore = msg.my_score || 0;
// ... rest unchanged, but renderQAScreen now receives msg.qa_questions without myName

// In case 'scores':
// This message type no longer exists for participants (replaced by personalized state)
// Remove the case or ignore it
```

- [ ] **Step 6: Update Q&A to use WebSocket and is_own/has_upvoted**

Replace `submitQuestion()`:
```javascript
function submitQuestion() {
    const input = document.getElementById('qa-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text || !ws) return;
    ws.send(JSON.stringify({ type: 'qa_submit', text }));
    input.value = '';
    input.focus();
}
```

Replace `upvoteQuestion()`:
```javascript
function upvoteQuestion(questionId) {
    if (!ws) return;
    ws.send(JSON.stringify({ type: 'qa_upvote', question_id: questionId }));
}
```

Update `renderQAScreen()` — no longer needs `myName` parameter:
```javascript
function renderQAScreen(questions) { ... }
```

Update `updateQAList()` — use `is_own` and `has_upvoted` from server:
```javascript
function updateQAList(questions) {
    // ...
    list.innerHTML = questions.map(q => {
        const isOwn = q.is_own;
        const hasUpvoted = q.has_upvoted;
        const canUpvote = !isOwn && !hasUpvoted;
        // ... rest unchanged
    }).join('');
}
```

- [ ] **Step 7: Commit**

```bash
git add static/participant.js static/participant.html
git commit -m "feat: participant UUID identity, inline name editing, WS-based Q&A"
```

---

### Task 7: Frontend host.js — consume new participant list format

**Files:**
- Modify: `static/host.js:134-168,224-256`

- [ ] **Step 1: Update host.js state message handling**

The host now receives `participants` as a list of objects. Update message handler:

```javascript
// In state message handler, replace lines 143-146 with:
if (msg.participants) {
    // Build backward-compat structures from participant objects
    participantLocations = {};
    scores = {};
    const names = [];
    msg.participants.forEach(p => {
        names.push(p.name);
        participantLocations[p.name] = p.location;
        scores[p.name] = p.score;
    });
    cachedNames = names;
    renderParticipantList(names);
} else {
    // Fallback for participant_count messages
    participantLocations = msg.locations || participantLocations;
    if (msg.names) renderParticipantList(msg.names);
}
```

And update `participant_count` handler:
```javascript
} else if (msg.type === 'participant_count') {
    document.getElementById('pax-count').textContent = msg.count;
    if (msg.participants) {
        participantLocations = {};
        scores = {};
        const names = [];
        msg.participants.forEach(p => {
            names.push(p.name);
            participantLocations[p.name] = p.location;
            scores[p.name] = p.score;
        });
        cachedNames = names;
        renderParticipantList(names);
    } else {
        participantLocations = msg.locations || participantLocations;
        renderParticipantList(msg.names || cachedNames);
    }
```

Remove the `scores` message type handler (line 166-168) — scores are now in state messages.

- [ ] **Step 2: Commit**

```bash
git add static/host.js
git commit -m "feat: host.js consumes new participant list format with UUID-backed data"
```

---

### Task 8: Update other broadcast callers

**Files:**
- Modify: `routers/wordcloud.py`
- Modify: `routers/activity.py`
- Modify: `routers/scores.py`

- [ ] **Step 1: Update all routers that call broadcast(build_state_message())**

In every router that imports and calls `broadcast(build_state_message())`, change to `broadcast_state()`:

```python
from messaging import broadcast_state
# Replace: await broadcast(build_state_message())
# With: await broadcast_state()
```

Check: `wordcloud.py`, `activity.py`, and any other routers.

- [ ] **Step 2: Fix scores.py — raw scores broadcast uses UUID keys**

`scores.py` line 15 broadcasts `{"type": "scores", "scores": state.scores}` which will now contain UUID keys. Replace with `broadcast_state()`:

```python
from messaging import broadcast_state

@router.delete("/api/scores", dependencies=[Depends(require_host_auth)])
async def reset_scores():
    state.scores = {}
    state.base_scores = {}
    await broadcast_state()
    return {"ok": True}
```

- [ ] **Step 3: Fix /api/status participant count — filter unnamed UUIDs**

In `poll.py`, update the `/api/status` endpoint to only count named participants:

```python
from messaging import participant_ids

@router.get("/api/status")
async def status():
    return {
        "backend_version": get_backend_version(),
        "participants": len(participant_ids()),
        "poll": state.poll,
        "poll_active": state.poll_active,
        "vote_counts": state.vote_counts(),
        "total_votes": len(state.votes),
    }
```

- [ ] **Step 4: Commit**

```bash
git add routers/wordcloud.py routers/activity.py routers/scores.py routers/poll.py
git commit -m "refactor: all routers use broadcast_state() for personalized messaging"
```

---

### Task 9: Update test_main.py — full test migration

**Files:**
- Modify: `test_main.py`

- [ ] **Step 1: Update DSL to use UUIDs**

Update `WorkshopSession.participant()` and `ParticipantSession`:

```python
import uuid as uuid_mod

class ParticipantSession:
    def __init__(self, ws, name: str, uuid: str):
        self._ws = ws
        self.name = name
        self.uuid = uuid
        self._last_state: dict = {}
        # Send set_name as first message
        self._ws.send_text(json.dumps({"type": "set_name", "name": name}))
        self._receive_initial_state()

    def assert_score(self, expected_pts: int):
        actual = state.scores.get(self.uuid, 0)
        assert actual == expected_pts, f"{self.name}: score={actual}, expected {expected_pts}"

    def assert_no_score(self):
        assert self.uuid not in state.scores or state.scores[self.uuid] == 0, (
            f"{self.name}: expected no score but got {state.scores.get(self.uuid)}"
        )

    # ... rest of assertions unchanged, except use my_score from state messages
```

Update `WorkshopSession.participant()`:

```python
@contextmanager
def participant(self, name: str):
    uid = str(uuid_mod.uuid4())
    with self._client.websocket_connect(f"/ws/{uid}") as ws:
        yield ParticipantSession(ws, name, uid)
```

Update `get_scores()`:
```python
def get_scores(self) -> dict:
    """Return scores keyed by display name (for test readability)."""
    return {state.participant_names.get(uid, uid): pts for uid, pts in state.scores.items()}
```

- [ ] **Step 2: Update Q&A tests to use WebSocket instead of REST**

The `TestQA._submit()` method needs to go through WebSocket now. Since tests need a participant connection for Q&A, update:

```python
def _submit_via_ws(self, session, name, text) -> str:
    uid = str(uuid_mod.uuid4())
    with session._client.websocket_connect(f"/ws/{uid}") as ws:
        ws.send_text(json.dumps({"type": "set_name", "name": name}))
        msg = json.loads(ws.receive_text())  # initial state
        ws.send_text(json.dumps({"type": "qa_submit", "text": text}))
        # Receive broadcast state
        for _ in range(10):
            msg = json.loads(ws.receive_text())
            if msg["type"] == "state":
                break
    return list(state.qa_questions.keys())[-1]  # last added question
```

Update upvote tests similarly.

- [ ] **Step 3: Update location test**

```python
def test_location_message_is_stored(self, session):
    with session.participant("Alice") as alice:
        alice.send_location("Bucharest, Romania")
        alice._recv("participant_count")
        assert state.locations.get(alice.uuid) == "Bucharest, Romania"
```

- [ ] **Step 4: Update standalone wordcloud tests (lines 610-713)**

There are 7 standalone wordcloud tests that connect directly via `client.websocket_connect("/ws/Alice")` bypassing the DSL. Each must be updated to:
1. Generate a UUID: `uid = str(uuid_mod.uuid4())`
2. Connect via `/ws/{uid}`
3. Send `set_name` before any other message

Example for `test_wordcloud_word_increments_count`:
```python
def test_wordcloud_word_increments_count():
    state.reset()
    session = WorkshopSession()
    session.open_wordcloud()
    client = TestClient(app)
    uid = str(uuid_mod.uuid4())
    with client.websocket_connect(f"/ws/{uid}") as ws_alice:
        alice = ParticipantSession(ws_alice, "Alice", uid)  # constructor sends set_name
        alice.submit_word("microservices")
        alice.assert_wordcloud_word("microservices", 1)
```

Apply same pattern to: `test_wordcloud_word_normalizes`, `test_wordcloud_word_awards_200_pts`, `test_wordcloud_word_rejected_when_not_active`.

For `test_wordcloud_word_host_gets_no_pts`: uses `__host__` which is auto-named "Host" on connect. Skip `ParticipantSession` constructor's `set_name` by connecting directly:
```python
def test_wordcloud_word_host_gets_no_pts():
    state.reset()
    session = WorkshopSession()
    session.open_wordcloud()
    client = TestClient(app)
    with client.websocket_connect("/ws/__host__") as ws_host:
        host = ParticipantSession(ws_host, "__host__", "__host__")
        host.submit_word("complexity")
        assert state.scores.get("__host__", 0) == 0
```

- [ ] **Step 5: Update scoring tests that reference state.scores by name**

All `session.get_scores()` calls now return name-keyed dict (resolved in the method). The parametrized multi-select tests and speed tests reference `state.vote_times` by name — change to UUID.

For `test_faster_voter_scores_higher`, update the backdating line:
```python
state.vote_times[slow.uuid] = state.vote_times.get(slow.uuid, datetime.now(timezone.utc)) - timedelta(seconds=20)
```

- [ ] **Step 6: Run all tests**

Run: `python3 -m pytest test_main.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add test_main.py
git commit -m "test: migrate all tests to UUID-based participant identity"
```

---

### Task 10: Update test_e2e.py and page objects

**Files:**
- Modify: `test_e2e.py`
- Modify: `pages/participant_page.py`

- [ ] **Step 1: Check page objects for name-dependent logic**

Read `pages/participant_page.py` and `pages/host_page.py`. The `join()` method should still work — it just fills the name input and clicks join. The UUID is generated client-side in JS. Page objects should need minimal changes.

- [ ] **Step 2: Remove/update TestNameUniqueness**

`TestNameUniqueness.test_duplicate_name_rejected_and_error_shown` must be **removed** — duplicate names are now allowed.

`test_autojoin_with_saved_name_no_js_error` needs to also set `workshop_participant_uuid` in localStorage for the auto-join to work (since UUID is now needed).

- [ ] **Step 3: Update Q&A e2e tests**

Q&A submit and upvote now go through WebSocket, not REST. The participant page object methods (`submit_question`, `upvote_question`) that interact with the UI should still work — they click buttons in the browser, and the JS sends WS messages. Verify these work.

The `clean_qa` fixture calls `_api(server_url, "post", "/api/qa/clear")` — this REST endpoint still exists (host-only). This is fine.

- [ ] **Step 4: Run e2e tests**

Run: `python3 -m pytest test_e2e.py -v --timeout=120 -m "not prod"`
Expected: ALL PASS (except possibly the removed duplicate-name test)

- [ ] **Step 5: Commit**

```bash
git add test_e2e.py pages/participant_page.py
git commit -m "test: update e2e tests for UUID-based identity, remove duplicate name test"
```

---

### Task 11: Final verification — run ALL tests

- [ ] **Step 1: Run unit tests**

Run: `python3 -m pytest test_main.py -v`
Expected: ALL PASS

- [ ] **Step 2: Run e2e tests**

Run: `python3 -m pytest test_e2e.py -v --timeout=120 -m "not prod"`
Expected: ALL PASS

- [ ] **Step 3: Manual smoke test**

Start server: `python3 -m uvicorn main:app --reload --port 8000`
1. Open `/host` in browser — verify cookie is set
2. Open `/` in two tabs — verify each tab gets a different UUID (check sessionStorage)
3. Join with the same name in both tabs — verify both connect successfully
4. Rename one participant inline — verify host sees the change
5. Submit a Q&A question — verify it appears for host and other participant
6. Upvote a question — verify counts update

- [ ] **Step 4: Final commit with any fixes**

```bash
git add -A
git commit -m "fix: address issues found during final verification"
```
