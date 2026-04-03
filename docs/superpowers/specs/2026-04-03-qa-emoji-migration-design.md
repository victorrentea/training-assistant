# Phase 4b: Q&A + Emoji Reaction Migration

## Problem

Phase 4a proved the broadcast infrastructure with word cloud migration. Now we migrate two more features end-to-end: Q&A (stateful, personalized) and emoji reactions (stateless, fire-and-forget).

Key architectural challenge: the host browser connects directly to daemon's localhost:8081, NOT through Railway. When daemon needs to push messages to the host (emoji reactions, Q&A updates), it must send them directly over the host's local WebSocket connection. This requires new infrastructure: a host WS push mechanism on the daemon side.

## Goal

- Build host WS push infrastructure: daemon can inject messages into the host browser's local WS connection.
- Migrate emoji reactions: participant REST call to daemon, daemon forwards to host (local WS) and desktop overlay (HTTP POST to victor-macos-addons at localhost:56789).
- Migrate Q&A end-to-end: state, participant submit/upvote, host submit/edit/delete/answered/clear, broadcasts with client-side personalization.
- No backward compat sync for Q&A (Railway's qa_questions goes stale; old cached JS must refresh).

## Architecture

### Host WS Push

```
Host Browser              Daemon localhost:8081
                          ┌──────────────────────────────────┐
  ws://localhost:8081/     │  host_server.py                  │
  ws/{sid}/__host__   ←──→│    proxy_websocket()              │
                          │    ↕ stores client_ws in host_ws  │
                          │                                    │
                          │  Daemon routers                    │
                          │    emoji_router.send_to_host()  ──→│──→ host browser
                          │    qa_router.send_to_host()     ──→│──→ host browser
                          └──────────────────────────────────┘
```

The host browser connects to `ws://localhost:8081/ws/{session_id}/__host__`. The WS proxy in `daemon/host_proxy.py` currently just shuttles frames between the host browser and Railway. We modify it to also store the `client_ws` reference in a `daemon/host_ws.py` module so daemon code can push messages directly.

### Emoji Flow

```
Participant Browser       Railway BE                    Daemon

POST /api/participant/
  emoji/reaction
  {emoji: "🎉"}      →   proxy_to_daemon()
                          proxy_request via WS      →   daemon emoji router
                                                        validates emoji
                                                        POST localhost:56789 (overlay)
                                                        send_to_host({type:"emoji_reaction",emoji:"🎉"})
                                                        returns {ok: true}
                                                   ←    proxy_response
                     ←    HTTP 200 {ok: true}
```

No state, no scoring, no broadcast to participants, no write-back events. The emoji goes directly to host browser (local WS) and desktop overlay (HTTP POST).

### Q&A Flow — Participant Submit

```
Participant Browser       Railway BE                    Daemon

POST /api/participant/
  qa/submit
  {text: "..."}      →   proxy_to_daemon()
                          proxy_request via WS      →   daemon qa router
                                                        validates, creates question
                                                        builds question list

                                                        write-back events:
                                                   ←    {type: "broadcast",
                                                          event: {type: "qa_updated",
                                                                  questions: [...]}}
                          _handle_broadcast fans
                          to all participant WSs
  ←  ws.onmessage                                  ←    {type: "score_award",
     {type: "qa_updated",                                 participant_id: "uuid",
      questions: [...]}                                   points: 100}
                          adds score, calls
                          broadcast_state()

                                                        send_to_host({type:"qa_updated",
                                                          questions: [...]})
                                                        → host browser (local WS)

                                                   ←    proxy_response
                     ←    HTTP 200 {ok: true}
```

### Q&A Flow — Host Actions

```
Host Browser              Daemon localhost:8081

POST /api/{sid}/qa/submit
  {text: "..."}      →   daemon qa host_router
                          creates question (no scoring)
                          builds question list
                          _send_qa_events():
                            ws_client.send(broadcast)  → Railway → all participants
                            send_to_host(qa_updated)   → host browser (local WS)
                     ←    {ok: true}
```

Host edit/delete/answered/clear follow the same pattern: mutate state, send broadcast via `_ws_client`, send to host via `send_to_host()`.

## Host WS Push Infrastructure

### New module: `daemon/host_ws.py`

```python
_host_ws = None  # WebSocket | None

def set_host_ws(ws):
    global _host_ws
    _host_ws = ws

def clear_host_ws():
    global _host_ws
    _host_ws = None

async def send_to_host(msg: dict):
    if _host_ws is None:
        return
    import json
    try:
        await _host_ws.send_text(json.dumps(msg))
    except Exception:
        pass
```

Single connection. Set when host connects to the WS proxy on localhost:8081 (path ends with `__host__`). Cleared on disconnect.

**Threading note:** `send_to_host()` is async and runs on uvicorn's event loop (same thread as the WS proxy and daemon routers). No lock needed. The only cross-thread concern is if `_host_ws` is set/cleared from a different thread — but both `set_host_ws` and `clear_host_ws` are called from the WS proxy handler which runs on the same uvicorn event loop.

### Modification to `daemon/host_proxy.py`

In `proxy_websocket()`, detect when `path` ends with `__host__`:

```python
async def proxy_websocket(client_ws: WebSocket, path: str, backend_ws_url: str):
    from daemon.host_ws import set_host_ws, clear_host_ws

    await client_ws.accept()

    is_host = path.endswith("__host__")
    if is_host:
        set_host_ws(client_ws)

    # ... existing proxy logic ...

    # In finally block:
    finally:
        if is_host:
            clear_host_ws()
        try:
            await client_ws.close()
        except Exception:
            pass
```

## Emoji Router

### New module: `daemon/emoji/router.py`

```python
_ws_client = None

def set_ws_client(client):
    global _ws_client
    _ws_client = client

participant_router = APIRouter(prefix="/api/participant/emoji", tags=["emoji"])

@participant_router.post("/reaction")
async def emoji_reaction(request: Request):
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    emoji = str(body.get("emoji", "")).strip()
    if not emoji or len(emoji) > 4:
        return JSONResponse({"error": "Invalid emoji"}, status_code=400)

    # Forward to host browser (local WS)
    from daemon.host_ws import send_to_host
    await send_to_host({"type": "emoji_reaction", "emoji": emoji})

    # Forward to desktop overlay (victor-macos-addons)
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            await client.post("http://localhost:56789/emoji",
                              json={"emoji": emoji}, timeout=1.0)
    except Exception:
        pass  # overlay may not be running

    return JSONResponse({"ok": True})
```

No state, no scoring, no write-back events. The `send_to_host` call is `await`ed because it's an async function running on the same event loop.

**Note on httpx client:** Creating a new `httpx.AsyncClient` per request is acceptable here since emoji reactions are infrequent (a few per minute at most). A shared client would be premature optimization.

## Q&A State

### New module: `daemon/qa/state.py`

```python
class QAState:
    def __init__(self):
        self._lock = threading.Lock()
        self.questions: dict[str, dict] = {}

    def sync_from_restore(self, data: dict):
        with self._lock:
            if "qa_questions" in data:
                self.questions.clear()
                # Convert upvoters from list (JSON) back to set
                for qid, q in data["qa_questions"].items():
                    self.questions[qid] = {
                        **q,
                        "upvoters": set(q.get("upvoters", [])),
                    }

    def submit(self, author: str, text: str) -> str:
        qid = str(uuid.uuid4())
        self.questions[qid] = {
            "id": qid,
            "text": text,
            "author": author,
            "upvoters": set(),
            "answered": False,
            "timestamp": time.time(),
        }
        return qid

    def upvote(self, qid: str, pid: str) -> tuple[bool, str | None]:
        """Returns (success, author_pid). Success=False if invalid."""
        q = self.questions.get(qid)
        if not q or q["author"] == pid or pid in q["upvoters"]:
            return False, None
        q["upvoters"].add(pid)
        return True, q["author"]

    def edit_text(self, qid: str, text: str) -> bool:
        q = self.questions.get(qid)
        if not q:
            return False
        q["text"] = text
        return True

    def delete(self, qid: str) -> bool:
        return self.questions.pop(qid, None) is not None

    def toggle_answered(self, qid: str, answered: bool) -> bool:
        q = self.questions.get(qid)
        if not q:
            return False
        q["answered"] = answered
        return True

    def clear(self):
        self.questions.clear()

    def build_question_list(self, names: dict[str, str], avatars: dict[str, str]) -> list[dict]:
        """Build sorted question list for broadcast.

        Resolves author UUIDs to display names daemon-side (participant JS
        does NOT have participant name/avatar maps). Includes author_uuid
        so participant JS can compute is_own, and upvoters as UUID list so
        participant JS can compute has_upvoted.
        """
        questions = []
        for qid, q in sorted(
            self.questions.items(),
            key=lambda item: (-len(item[1]["upvoters"]), item[1]["timestamp"]),
        ):
            questions.append({
                "id": qid,
                "text": q["text"],
                "author": names.get(q["author"], "Unknown"),
                "author_uuid": q["author"],
                "author_avatar": avatars.get(q["author"], ""),
                "upvoters": list(q["upvoters"]),
                "upvote_count": len(q["upvoters"]),
                "answered": q["answered"],
                "timestamp": q["timestamp"],
            })
        return questions

qa_state = QAState()
```

**Key design choice — daemon-side name resolution:** `build_question_list()` resolves `author` UUID to display name using the daemon's `participant_state.participant_names` map (same data Railway's state_builder uses). This avoids sending raw UUIDs to participants and avoids requiring participant JS to maintain name/avatar maps (which it currently does not have). The broadcast includes:
- `author`: resolved display name (for rendering)
- `author_uuid`: raw UUID (for `is_own` check)
- `author_avatar`: resolved avatar (for rendering)
- `upvoters`: UUID list (for `has_upvoted` check)
- `upvote_count`: precomputed count (for rendering)

Participant JS computes only `is_own` (compare `author_uuid` to own UUID) and `has_upvoted` (check own UUID in `upvoters` list).

**Sorting:** Same as Railway — by upvote count descending, then timestamp ascending.

**sync_from_restore data format:** Railway's `daemon_state_push` sends `qa_questions` as a dict of question objects. The `upvoters` field arrives as a JSON list (sets are serialized to lists by `send_json`). `sync_from_restore` converts back to sets.

## Q&A Router

### New module: `daemon/qa/router.py`

**Participant router** (proxied via Railway):

```python
_ws_client = None

def set_ws_client(client):
    global _ws_client
    _ws_client = client

participant_router = APIRouter(prefix="/api/participant/qa", tags=["qa"])

def _build_questions():
    """Helper: build question list with resolved names."""
    return qa_state.build_question_list(
        participant_state.participant_names,
        participant_state.participant_avatars,
    )

@participant_router.post("/submit")
async def submit_question(request: Request):
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    text = str(body.get("text", "")).strip()
    if not text or len(text) > 280:
        return JSONResponse({"error": "Invalid text"}, status_code=400)

    # No activity gate — Railway's qa_submit handler accepts submissions regardless
    # of current activity, and we preserve that behavior.

    qa_state.submit(pid, text)
    questions = _build_questions()

    request.state.write_back_events = [
        {"type": "broadcast", "event": {"type": "qa_updated", "questions": questions}},
        {"type": "score_award", "participant_id": pid, "points": 100},
    ]

    # Send to host directly via local WS
    from daemon.host_ws import send_to_host
    await send_to_host({"type": "qa_updated", "questions": questions})

    return JSONResponse({"ok": True})

@participant_router.post("/upvote")
async def upvote_question(request: Request):
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    question_id = str(body.get("question_id", ""))
    if not question_id:
        return JSONResponse({"error": "Missing question_id"}, status_code=400)

    success, author_pid = qa_state.upvote(question_id, pid)
    if not success:
        return JSONResponse({"error": "Cannot upvote"}, status_code=409)

    questions = _build_questions()

    request.state.write_back_events = [
        {"type": "broadcast", "event": {"type": "qa_updated", "questions": questions}},
        {"type": "score_award", "participant_id": author_pid, "points": 50},
        {"type": "score_award", "participant_id": pid, "points": 25},
    ]

    from daemon.host_ws import send_to_host
    await send_to_host({"type": "qa_updated", "questions": questions})

    return JSONResponse({"ok": True})
```

**Host router** (daemon localhost):

```python
host_router = APIRouter(prefix="/api/{session_id}/qa", tags=["qa"])

@host_router.post("/submit")
async def host_submit_question(request: Request):
    body = await request.json()
    text = str(body.get("text", "")).strip()
    if not text or len(text) > 280:
        return JSONResponse({"error": "Invalid text"}, status_code=400)
    # Host submits as "__host__" author — no scoring
    qa_state.submit("__host__", text)
    await _send_qa_events()
    return JSONResponse({"ok": True})

@host_router.put("/question/{question_id}/text")
async def edit_question_text(question_id: str, request: Request):
    body = await request.json()
    text = str(body.get("text", "")).strip()
    if not text or len(text) > 280:
        return JSONResponse({"error": "Invalid text"}, status_code=400)
    if not qa_state.edit_text(question_id, text):
        return JSONResponse({"error": "Not found"}, status_code=404)
    await _send_qa_events()
    return JSONResponse({"ok": True})

@host_router.delete("/question/{question_id}")
async def delete_question(question_id: str):
    if not qa_state.delete(question_id):
        return JSONResponse({"error": "Not found"}, status_code=404)
    await _send_qa_events()
    return JSONResponse({"ok": True})

@host_router.put("/question/{question_id}/answered")
async def toggle_answered(question_id: str, request: Request):
    body = await request.json()
    answered = bool(body.get("answered", False))
    if not qa_state.toggle_answered(question_id, answered):
        return JSONResponse({"error": "Not found"}, status_code=404)
    await _send_qa_events()
    return JSONResponse({"ok": True})

@host_router.post("/clear")
async def clear_qa():
    qa_state.clear()
    await _send_qa_events()
    return JSONResponse({"ok": True})


async def _send_qa_events():
    """Send broadcast to participants (via Railway) and to host (local WS)."""
    questions = _build_questions()
    if _ws_client:
        _ws_client.send({
            "type": "broadcast",
            "event": {"type": "qa_updated", "questions": questions},
        })
    from daemon.host_ws import send_to_host
    await send_to_host({"type": "qa_updated", "questions": questions})
```

## daemon_state_push Extension

Railway's `daemon_state_push` (in `features/ws/router.py`) must include Q&A state:

```python
"qa_questions": {qid: {**q, "upvoters": list(q["upvoters"])} for qid, q in state.qa_questions.items()},
```

The `upvoters` set must be converted to a list for JSON serialization. Daemon's `qa_state.sync_from_restore()` converts it back.

## Participant JS Changes

### `static/participant.js`

**Q&A submit:** Replace `sendWS('qa_submit', { text })` with `participantApi('qa/submit', { text })`.

**Q&A upvote:** Replace `sendWS('qa_upvote', { question_id: questionId })` with `participantApi('qa/upvote', { question_id: questionId })`.

**Emoji:** Replace `sendWS('emoji_reaction', { emoji })` with `participantApi('emoji/reaction', { emoji })`.

**New WS handler for `qa_updated`:** Add case in message handler:
```javascript
case 'qa_updated':
    // Daemon already resolved author names/avatars and computed upvote_count.
    // Client only needs to add is_own and has_upvoted using author_uuid and upvoters.
    const myQuestions = (msg.questions || []).map(q => ({
        ...q,
        is_own: q.author_uuid === myUUID,
        has_upvoted: (q.upvoters || []).includes(myUUID),
    }));
    renderQAScreen(myQuestions);
    break;
```

**Field mapping:** The broadcast includes `author` (display name), `author_avatar`, `upvote_count`, `author_uuid`, and `upvoters` (UUID list). The existing `renderQAScreen` / `updateQAList` functions consume `author`, `author_avatar`, `upvote_count`, `is_own`, `has_upvoted` — all present after the mapping above. No name/avatar maps needed on the client.

**`myUUID` availability:** `myUUID` is already a module-level variable in participant.js (set from localStorage).

## Host JS Changes

### `static/host.js`

**Host Q&A submit:** Replace `sendWS('qa_submit', { text })` with:
```javascript
fetch(API('/qa/submit'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text })
});
```

**Host Q&A edit/delete/answered/clear:** These already use `fetch(API('/qa/...'))` — they will route through daemon localhost to the new `host_router` before hitting the catch-all proxy. **No JS changes needed** for these endpoints.

**Emoji:** Host does not send emojis (only receives them). The `emoji_reaction` WS message from daemon arrives via the local WS connection and is already handled by `showHostEmoji()`. **No JS changes needed** for host emoji display.

**New WS handler for `qa_updated`:** Add case in host message handler:
```javascript
case 'qa_updated':
    // Daemon already resolved names/avatars and computed upvote_count.
    // Host view: no is_own/has_upvoted needed — pass through directly.
    renderQAList(msg.questions || []);
    break;
```

## Backward Compatibility

- Old WS `qa_submit`, `qa_upvote`, `emoji_reaction` handlers in `features/ws/router.py` stay for old cached JS.
- No `qa_state_sync` — Railway's `qa_questions` goes stale. Participants with old cached JS must refresh.
- Railway's Q&A REST endpoints (`features/qa/router.py`) become dead code once daemon handles them. Left in place.
- Prometheus counters (`qa_questions_total`, `qa_upvotes_total`) stay on Railway — they'll go stale for new-path requests.
- `score_award` triggers `broadcast_state()` on Railway — still provides `my_score` to participants until scoring migrates.
- **Known limitation:** `author_avatar` in conference mode uses `"letter:XX:color"` format which the Q&A `<img>` tag can't render (shows broken image). This is a pre-existing bug in Railway's state_builder — not introduced by this migration. Will be fixed separately.

## Testing Strategy

- **`tests/daemon/test_emoji_router.py`**: emoji reaction endpoint (happy path, validation, host_ws send verification, overlay POST verification)
- **`tests/daemon/test_qa_router.py`**: participant submit/upvote (happy path, validation, duplicate upvote, self-upvote), host submit/edit/delete/answered/clear, write-back events, host_ws send verification
- **`tests/daemon/test_qa_state.py`**: QAState unit tests (submit, upvote, edit, delete, toggle_answered, clear, build_question_list sorting, sync_from_restore)
- **`tests/daemon/test_host_ws.py`**: host WS module (set/clear/send_to_host)
- **Existing tests**: must still pass

## Files Changed

### New files
- `daemon/host_ws.py` — host WS push module (single connection)
- `daemon/emoji/__init__.py` — package init
- `daemon/emoji/router.py` — emoji reaction endpoint
- `daemon/qa/__init__.py` — package init
- `daemon/qa/state.py` — Q&A state cache
- `daemon/qa/router.py` — participant + host Q&A endpoints
- `tests/daemon/test_host_ws.py` — host WS module tests
- `tests/daemon/test_emoji_router.py` — emoji router tests
- `tests/daemon/test_qa_router.py` — Q&A router tests
- `tests/daemon/test_qa_state.py` — Q&A state tests

### Modified files
- `daemon/host_proxy.py` — store host WS reference on connect/disconnect
- `daemon/host_server.py` — mount emoji + Q&A routers before catch-all
- `daemon/__main__.py` — register daemon_state_push for Q&A state, set ws_client on emoji + Q&A routers
- `features/ws/router.py` — extend daemon_state_push with qa_questions
- `static/participant.js` — replace qa_submit/qa_upvote/emoji WS calls with REST; add qa_updated handler with client-side personalization
- `static/host.js` — replace host qa_submit WS call with REST; add qa_updated handler
