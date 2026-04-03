# Phase 4a: Broadcast Infrastructure + Word Cloud Migration

## Problem

Phase 3 established the REST proxy for participant calls to daemon. But there's no mechanism for the daemon to push broadcast events back to participants. Currently all broadcasts originate from Railway's `broadcast_state()`, which sends personalized state dumps. The target architecture has the daemon sending semantic events that Railway fans out blindly.

We need:
1. Generic broadcast infrastructure: daemon sends an event, Railway fans it to all participant WSs.
2. A first end-to-end feature migration (word cloud) to prove the broadcast path works alongside the existing REST proxy.

## Goal

- Build a generic broadcast fan-out handler on Railway: daemon sends `{type: "broadcast", event: {...}}`, Railway extracts the inner event and sends it to all connected participant WSs unchanged.
- Migrate word cloud completely to daemon: participant word submission, host topic/clear/word, all state, and broadcasts.
- Keep backward compatibility: Railway's AppState word cloud fields stay in sync via write-back events so features not yet migrated (like the full `broadcast_state()` path) still work.

## Architecture

```
Participant Browser          Railway BE                         Daemon

POST /api/participant/
  wordcloud/word
  {word: "testing"}     →   catch-all proxy route
                             (already exists from Phase 3)
                             proxy_request via daemon WS    →   daemon wordcloud router
                                                                validates, increments count

                                                                sends write-back events:

                                                           ←   {type: "broadcast",
                                                                 event: {
                                                                   type: "wordcloud_updated",
                                                                   words: {...},
                                                                   word_order: [...],
                                                                   topic: "..."}}

                             _handle_broadcast extracts
                             inner event, sends to ALL
                             participant WSs
  ←  ws.onmessage                                          ←   {type: "wordcloud_state_sync",
     {type: "wordcloud_                                          words: {...},
      updated", ...}                                             word_order: [...],
                                                                 topic: "..."}
                             updates AppState wordcloud
                             fields (backward compat)

                                                           ←   {type: "score_award",
                                                                 participant_id: "uuid",
                                                                 points: 200}
                             adds score, calls
                             broadcast_state()

                                                                sends proxy_response:
                                                           ←   {type: "proxy_response",
                                                                 id: abc123, status: 200,
                                                                 body: {ok: true}}
                             resolves Future
                        ←    returns HTTP 200 {ok: true}
```

**Host word cloud calls** (topic, clear, word submission) go directly to daemon localhost — no Railway proxy involved:

```
Host Browser                 Daemon localhost:8081

POST /api/wordcloud/topic
  {topic: "AI"}         →   daemon wordcloud host router
                             updates state
                             sends broadcast + state sync
                             directly via ws_client.send()
                        ←    {ok: true}
```

**Ordering guarantee:** Same as Phase 3 — for proxied calls, daemon sends broadcast and write-back events BEFORE `proxy_response`. Since WS messages are ordered, Railway processes the broadcast fan-out before the HTTP response reaches the participant. For host-direct calls, the WS events are sent synchronously before the HTTP response is returned.

## Railway: Generic Broadcast Handler

### New handler in `features/ws/router.py`

```python
async def _handle_broadcast(data: dict):
    """Fan out a daemon broadcast event to all connected participant WSs."""
    event = data.get("event")
    if not event:
        return
    msg = json.dumps(event)
    for pid, ws in list(state.participants.items()):
        if pid.startswith("__"):  # skip __host__, __overlay__
            continue
        try:
            await ws.send_text(msg)
        except Exception:
            pass
```

Registered in `_DAEMON_MSG_HANDLERS` as `MSG_BROADCAST: _handle_broadcast`.

**Design choice:** This handler sends the event to participants only, not to host or overlay. Host and overlay connections in `state.participants` are keyed as `__host__` and `__overlay__` (verified in codebase). The host runs on daemon localhost and gets updates directly. The overlay will be addressed in a future phase.

### New handler for word cloud state sync

```python
async def _handle_wordcloud_state_sync(data: dict):
    """Keep Railway's AppState word cloud fields in sync with daemon."""
    if "words" in data:
        state.wordcloud_words = data["words"]
    if "word_order" in data:
        state.wordcloud_word_order = data["word_order"]
    if "topic" in data:
        state.wordcloud_topic = data["topic"]
```

No broadcast from this handler — the daemon already sent the broadcast via `_handle_broadcast`. This only updates Railway's AppState for backward compatibility (other features' `broadcast_state()` still includes word cloud data via `state_builder.py`).

### New handler for score awards

```python
async def _handle_score_award(data: dict):
    """Award points to a participant (daemon → Railway, transitional)."""
    pid = data.get("participant_id")
    points = data.get("points", 0)
    if pid and points:
        state.add_score(pid, points)
        await broadcast_state()
```

**Transitional note:** `broadcast_state()` sends a full personalized state dump to all participants. This is redundant with the `wordcloud_updated` broadcast that already reached participants, but it's needed because `my_score` is delivered via the state dump. Once scoring migrates to daemon (Phase 5), this handler will be replaced by a `scores_updated` semantic event. Accepted as transitional cost.

## WS Message Types

### New messages

| Direction | Type | Payload |
|-----------|------|---------|
| Daemon → BE | `broadcast` | `{event: {type: str, ...}}` — generic, inner event sent to all participants unchanged |
| Daemon → BE | `wordcloud_state_sync` | `{words: dict, word_order: list, topic: str}` — keeps Railway AppState in sync |
| Daemon → BE | `score_award` | `{participant_id: str, points: int}` — reusable for all feature migrations until scoring moves to daemon |

Note on payload structure: `broadcast` nests its payload under `event:` (the inner event is extracted and forwarded). `wordcloud_state_sync` and `score_award` are flat (fields at the top level alongside `type`). This is intentional — `broadcast` wraps because the inner event is forwarded as-is to participants; sync events are consumed by Railway handlers directly.

### Constants added to `features/ws/daemon_protocol.py`

```python
# Generic broadcast (daemon → all participants via backend)
MSG_BROADCAST = "broadcast"

# Word cloud state sync (daemon → backend)
MSG_WORDCLOUD_STATE_SYNC = "wordcloud_state_sync"

# Score award (daemon → backend, transitional)
MSG_SCORE_AWARD = "score_award"
```

## Daemon: Word Cloud State

### New module: `daemon/wordcloud/state.py`

```python
class WordCloudState:
    def __init__(self):
        self._lock = threading.Lock()
        self.words: dict[str, int] = {}
        self.word_order: list[str] = []  # newest first
        self.topic: str = ""

    def sync_from_restore(self, data: dict):
        """Update from state_restore/session_sync. Called from main thread.

        Uses _lock because this runs on the main thread while mutation
        methods may run on uvicorn's event loop thread.
        """
        with self._lock:
            if "wordcloud_words" in data:
                self.words.clear()
                self.words.update(data["wordcloud_words"])
            if "wordcloud_word_order" in data:
                self.word_order.clear()
                self.word_order.extend(data["wordcloud_word_order"])
            if "wordcloud_topic" in data:
                self.topic = data["wordcloud_topic"]

    def add_word(self, word: str) -> dict:
        """Add a word, return current state for broadcast.

        Runs on uvicorn's single-threaded event loop — concurrent async
        handlers are serialized at await points, no lock needed.
        """
        word = word.strip().lower()
        if word not in self.words:
            self.word_order.insert(0, word)
        self.words[word] = self.words.get(word, 0) + 1
        return self.snapshot()

    def set_topic(self, topic: str) -> dict:
        self.topic = topic.strip()
        return self.snapshot()

    def clear(self) -> dict:
        self.words.clear()
        self.word_order.clear()
        self.topic = ""
        return self.snapshot()

    def snapshot(self) -> dict:
        return {
            "words": dict(self.words),
            "word_order": list(self.word_order),
            "topic": self.topic,
        }

wordcloud_state = WordCloudState()
```

**Threading model:** Same as `ParticipantState` from Phase 3. Mutation methods (`add_word`, `set_topic`, `clear`) run on uvicorn's single-threaded event loop — no lock needed. `sync_from_restore()` runs on the main thread (via `drain_queue()`) and acquires `_lock`. The cross-thread race window exists (same as `ParticipantState`) but is acceptable — `sync_from_restore` only runs on daemon reconnect, which is a rare event.

## Daemon: Word Cloud Router

### New module: `daemon/wordcloud/router.py`

Contains two routers and a module-level `_ws_client` reference.

**`ws_client` injection:** The module exposes `_ws_client = None` at module level. During daemon startup, `__main__.py` sets it: `wordcloud_router._ws_client = ws_client`. The host router endpoints use `_ws_client.send()` directly to send WS events. This is the same injection pattern used for other daemon modules that need WS access.

**`ws_client.send()` in async context:** `DaemonWsClient.send()` is a fast synchronous call (json.dumps + ws.send under a lock). Calling it from an async FastAPI handler does not materially block the event loop — the actual I/O is a single small frame write. Acceptable without `run_in_executor`.

**Participant router** (proxied via Railway):

```python
participant_router = APIRouter(prefix="/api/participant/wordcloud", tags=["wordcloud"])

@participant_router.post("/word")
async def submit_word(request: Request):
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    word = str(body.get("word", "")).strip()
    if not word or len(word) > 40:
        return JSONResponse({"error": "Invalid word"}, status_code=400)

    # Activity gate
    if participant_state.current_activity != "wordcloud":
        return JSONResponse({"error": "Word cloud not active"}, status_code=409)

    snapshot = wordcloud_state.add_word(word)

    # Write-back events: broadcast + state sync + scoring
    request.state.write_back_events = [
        {"type": "broadcast", "event": {"type": "wordcloud_updated", **snapshot}},
        {"type": "wordcloud_state_sync", **snapshot},
        {"type": "score_award", "participant_id": pid, "points": 200},
    ]

    return JSONResponse({"ok": True})
```

**Host router** (called directly on daemon localhost):

```python
host_router = APIRouter(prefix="/api/wordcloud", tags=["wordcloud"])

@host_router.post("/word")
async def host_submit_word(request: Request):
    """Host word submission — same as participant but no scoring."""
    body = await request.json()
    word = str(body.get("word", "")).strip()
    if not word or len(word) > 40:
        return JSONResponse({"error": "Invalid word"}, status_code=400)

    snapshot = wordcloud_state.add_word(word)
    _send_wordcloud_events(snapshot)
    return JSONResponse({"ok": True})

@host_router.post("/topic")
async def set_topic(request: Request):
    body = await request.json()
    topic = str(body.get("topic", "")).strip()
    snapshot = wordcloud_state.set_topic(topic)
    _send_wordcloud_events(snapshot)
    return JSONResponse({"ok": True})

@host_router.post("/clear")
async def clear_wordcloud(request: Request):
    snapshot = wordcloud_state.clear()
    _send_wordcloud_events(snapshot)
    return JSONResponse({"ok": True})


def _send_wordcloud_events(snapshot: dict):
    """Send broadcast + state sync directly via ws_client (host-direct path)."""
    if _ws_client is None:
        return
    _ws_client.send({
        "type": "broadcast",
        "event": {"type": "wordcloud_updated", **snapshot},
    })
    _ws_client.send({
        "type": "wordcloud_state_sync",
        **snapshot,
    })
```

**Two transport mechanisms:**
- **Participant path** (proxied via Railway): Write-back events in `request.state.write_back_events` → serialized to `X-Write-Back-Events` header → `proxy_handler` reads and sends over WS.
- **Host-direct path** (localhost): `_send_wordcloud_events()` calls `_ws_client.send()` directly. No proxy handler involved.

### Scoring

Word submission awards 200 points per word regardless of whether the word is new or a repeat. This matches the existing Railway behavior. The `score_award` write-back event is only sent for participant submissions (not host). Railway's `_handle_score_award` calls `state.add_score()` + `broadcast_state()`.

## Activity Gate

The daemon needs to know the current activity to reject stale word submissions. Add `current_activity: str` to `daemon/participant/state.py` (the existing `ParticipantState`). It's already present in `state_restore` data. The wordcloud router checks `participant_state.current_activity != "wordcloud"` before accepting words.

## Daemon: host_server.py Changes

Mount both routers BEFORE the catch-all `/api/{path:path}` proxy:

```python
from daemon.wordcloud.router import participant_router as wc_participant_router
from daemon.wordcloud.router import host_router as wc_host_router

app.include_router(wc_participant_router)  # /api/participant/wordcloud/*
app.include_router(wc_host_router)         # /api/wordcloud/*
# ... then catch-all ...
```

## Daemon: __main__.py Changes

1. On `state_restore` / `session_sync`, sync word cloud state:
   ```python
   from daemon.wordcloud.state import wordcloud_state
   wordcloud_state.sync_from_restore(data)
   ```

2. Set `ws_client` on the word cloud router module:
   ```python
   import daemon.wordcloud.router as wc_router
   wc_router._ws_client = ws_client
   ```

## Participant JS Changes

### `static/participant.js`

Replace word submission:
```javascript
// Before:
sendWS('wordcloud_word', { word });

// After:
participantApi('wordcloud/word', { word });
```

Add handler for `wordcloud_updated` event in the WS message handler:
```javascript
case 'wordcloud_updated':
    renderWordCloudScreen(msg.words || {}, msg.word_order || [], msg.topic || '');
    break;
```

The existing `renderWordCloudScreen` function works unchanged — just maps the new field names (`words` instead of `wordcloud_words`, `word_order` instead of `wordcloud_word_order`, `topic` instead of `wordcloud_topic`).

### `static/host.js`

Replace host word submission:
```javascript
// Before:
sendWS('wordcloud_word', { word });

// After:
fetch(API('/wordcloud/word'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ word })
});
```

This calls `/api/{session_id}/wordcloud/word` which goes through the daemon localhost to the `host_router` `POST /word` endpoint.

**No changes needed** for host topic/clear — those already use `fetch(API('/wordcloud/topic'))` and `fetch(API('/wordcloud/clear'))` which route through daemon localhost. They currently proxy to Railway; after mounting `host_router` on daemon, they'll be handled locally before hitting the catch-all proxy.

## Backward Compatibility

- Old WS `wordcloud_word` handler in `router.py` stays during migration (participants using old cached JS still work).
- Railway's `wordcloud_words`, `wordcloud_word_order`, `wordcloud_topic` on AppState are kept in sync via `wordcloud_state_sync` write-back.
- The existing `broadcast_state()` path still includes word cloud data (via `state_builder.py`) for non-migrated features.
- Host topic/clear endpoints on Railway (`features/wordcloud/router.py`) remain as dead code once the daemon handles them. Can be removed in a cleanup phase.
- `score_award` triggers `broadcast_state()` on Railway — this is a transitional redundancy. Once scoring moves to daemon, it will be replaced by a `scores_updated` semantic event.

## Testing Strategy

- **Unit tests** (`tests/daemon/test_wordcloud_router.py`): participant word submission (happy path, validation, activity gate), host word/topic/clear endpoints, scoring write-back events, ws_client send verification for host-direct path
- **Unit tests** (`tests/test_broadcast_handler.py`): Railway broadcast fan-out handler — sends to participants, skips `__host__`/`__overlay__`, handles dead connections
- **Existing tests**: must still pass

## Files Changed

### New files
- `daemon/wordcloud/__init__.py` — package init
- `daemon/wordcloud/state.py` — word cloud state cache
- `daemon/wordcloud/router.py` — participant + host word cloud endpoints + `_send_wordcloud_events` helper
- `tests/daemon/test_wordcloud_router.py` — daemon router unit tests
- `tests/test_broadcast_handler.py` — broadcast handler unit tests

### Modified files
- `features/ws/daemon_protocol.py` — add `MSG_BROADCAST`, `MSG_WORDCLOUD_STATE_SYNC`, `MSG_SCORE_AWARD`
- `features/ws/router.py` — add `_handle_broadcast`, `_handle_wordcloud_state_sync`, `_handle_score_award` handlers to `_DAEMON_MSG_HANDLERS`
- `daemon/host_server.py` — mount word cloud participant + host routers before catch-all
- `daemon/__main__.py` — sync word cloud state from `state_restore`; set `ws_client` on word cloud router module
- `daemon/participant/state.py` — add `current_activity: str` field to `ParticipantState` and `sync_from_restore`
- `static/participant.js` — replace `sendWS('wordcloud_word')` with `participantApi('wordcloud/word', ...)`; add `wordcloud_updated` WS event handler
- `static/host.js` — replace `sendWS('wordcloud_word')` with `fetch(API('/wordcloud/word'), ...)`
