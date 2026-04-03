# Phase 3: REST Proxy + Identity Migration to Daemon

## Problem

All participant interactions currently go through WebSocket messages handled inline in `features/ws/router.py` on Railway. The railway proxy redesign requires moving business logic to the daemon. We need:

1. A generic proxy mechanism so Railway can forward participant REST calls to daemon over the existing daemon WS connection.
2. The first feature migration (participant identity: set_name, avatar, location) to prove the full chain end-to-end.

## Goal

- Build a generic, catch-all REST proxy on Railway that forwards participant API calls to daemon via WS — no per-endpoint code on Railway, so adding/changing daemon endpoints requires no Railway redeployment.
- Move identity business logic (name validation, avatar assignment, conference mode, location) to a daemon-side FastAPI router.
- Daemon processes the request, writes results back to Railway via WS events, Railway updates AppState and broadcasts to participants.
- Keep backward compatibility: old WS message handlers remain on Railway until participant JS is fully switched over.

## Architecture

```
Participant Browser          Railway BE                         Daemon

POST /api/participant/name
  X-Participant-ID: {uuid}
  {name: "Alice"}       →   catch-all proxy route
                             /{sid}/api/participant/{path:path}

                             creates Future(id=abc123)
                             sends over daemon WS:
                             {type: proxy_request,
                              id: abc123,
                              method: POST,
                              path: /api/participant/name,
                              body: {name: "Alice"},
                              headers: {x-participant-id: uuid},
                              participant_id: uuid}     →    receives proxy_request

                             awaits Future (5s timeout)       routes to local FastAPI
                                                              daemon/participant/router.py
                                                              validates name, assigns avatar

                                                              sends participant_registered
                                                              BEFORE proxy_response:
                                                        ←    {type: participant_registered,
                                                              participant_id: uuid,
                                                              name: "Alice",
                                                              avatar: "letter:AL:#4a9",
                                                              ...}
                             updates AppState
                             broadcasts to all participants

                                                              then sends proxy_response:
                                                        ←    {id: abc123, status: 200,
                                                              body: {ok: true}, ...}
                             resolves Future
                        ←    returns HTTP 200 {ok: true}
```

**Ordering guarantee:** The daemon always sends state write-back events (`participant_registered`, etc.) *before* the `proxy_response`. This ensures Railway has updated AppState and broadcast to participants before the HTTP response reaches the calling participant. Since WS messages are ordered within a single connection, the write-back is always processed first.

## Railway: Generic Proxy Bridge

### New module: `features/ws/proxy_bridge.py`

Generic infrastructure — not specific to any feature:

```python
_pending_requests: dict[str, asyncio.Future] = {}

async def proxy_to_daemon(method: str, path: str, body: bytes | None,
                          headers: dict, participant_id: str | None) -> Response:
    """Forward a participant REST call to daemon via WS proxy_request/proxy_response."""
```

**Flow:**
1. Check `state.daemon_ws` is connected. If not → 503 "Trainer not connected".
2. Generate UUID correlation `id`.
3. Create `asyncio.Future`, store in `_pending_requests[id]`.
4. Send `proxy_request` message over daemon WS.
5. `await future` with 5-second timeout.
6. On timeout → cancel Future, remove from dict, return 503.
7. On response → return HTTP response with status/body/content_type from `proxy_response`.

**Daemon WS handler for `proxy_response`:**
- Registered in `_DAEMON_MSG_HANDLERS` but unlike other handlers it does **not** update AppState or trigger broadcasts.
- It only resolves the pending Future: looks up `_pending_requests[id]`, calls `future.set_result(data)`.
- Since the `proxy_response` handler runs on the same async event loop as the waiting `proxy_to_daemon()` coroutine (both inside Railway's FastAPI/uvicorn), `future.set_result(data)` is called directly — no `call_soon_threadsafe` needed.
- Unknown/expired IDs: log warning, discard.
- Malformed payloads (missing `id` or `status`): log warning, discard.

### Catch-all route (also in `features/ws/proxy_bridge.py`)

The catch-all route lives in the same module as the proxy infrastructure — no separate `features/participant/` package needed since Railway has zero business logic here:

```python
participant_proxy_router = APIRouter()

@participant_proxy_router.api_route("/api/participant/{path:path}",
                  methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def participant_proxy(request: Request, path: str):
    participant_id = request.headers.get("x-participant-id")
    return await proxy_to_daemon(
        method=request.method,
        path=f"/api/participant/{path}",
        body=await request.body(),
        headers=dict(request.headers),
        participant_id=participant_id,
    )
```

Mounted on the `session_participant` sub-app in `main.py` (no auth required), same as other participant-facing routes like `/api/suggest-name` and `/api/status`.

**No per-endpoint logic** — any endpoint the daemon defines under `/api/participant/` is automatically proxied.

**Future expansion:** When migrating more features, widen the prefix:
- Phase 3: `/api/participant/{path:path}`
- Later: `/api/poll/{path:path}`, `/api/qa/{path:path}`, etc.
- Final: `/api/{path:path}` (everything proxied, old routers removed)

## WS Message Types

### New messages

| Direction | Type | Payload |
|-----------|------|---------|
| BE → Daemon | `proxy_request` | `{id, method, path, body, headers, participant_id}` (body is UTF-8 string; binary bodies would need base64 in future phases) |
| Daemon → BE | `proxy_response` | `{id, status, body, content_type}` |
| Daemon → BE | `participant_registered` | `{participant_id, name, avatar, universe, score, debate_side?}` |
| Daemon → BE | `participant_location` | `{participant_id, location}` |
| Daemon → BE | `participant_avatar_updated` | `{participant_id, avatar}` |

### Constants added to `features/ws/daemon_protocol.py`

```python
# Proxy (both directions)
MSG_PROXY_REQUEST = "proxy_request"
MSG_PROXY_RESPONSE = "proxy_response"

# Identity events (daemon → backend)
MSG_PARTICIPANT_REGISTERED = "participant_registered"
MSG_PARTICIPANT_LOCATION = "participant_location"
MSG_PARTICIPANT_AVATAR_UPDATED = "participant_avatar_updated"
```

## Daemon: Participant Router

### New module: `daemon/participant/router.py`

FastAPI router mounted on the daemon's local host server:

```python
router = APIRouter(prefix="/api/participant", tags=["participant"])

@router.post("/name")
async def set_name(request: Request):
    """Validate name, assign avatar, handle conference mode."""
    pid = request.headers["x-participant-id"]
    body = await request.json()
    # ... business logic moved from features/ws/router.py ...

@router.post("/avatar")
async def refresh_avatar(request: Request):
    """Re-roll avatar (conference mode only)."""

@router.post("/location")
async def set_location(request: Request):
    """Store participant city/timezone."""
```

### Business logic moved from `features/ws/router.py`

The following logic moves to daemon (currently inline in `_handle_participant_connection()`):

**set_name:**
- **Returning participant fast path:** If `participant_id` already exists in daemon's local `participant_names` cache, skip validation/assignment — return the existing name/avatar immediately. The daemon updates its local cache but does NOT send `participant_registered` to Railway (Railway already has this state). This matches the current fast path in `features/ws/router.py` (lines 718-728).
- **New participant:** Name validation (non-empty, strip whitespace), avatar assignment (`letter:XX:#color` with deterministic color), universe assignment (conference mode), score initialization (0), debate late-joiner auto-assign (if debate is in arguments phase).
- **Conference mode auto-naming:** When mode is "conference" and the submitted name is empty (`""`), daemon auto-assigns a character name from the pool. This is triggered by participant JS, which calls `participantApi('name', {name: ''})` on WS connect when in conference mode (the JS already knows the mode from the initial state message).

**refresh_avatar:**
- Re-roll avatar (only in conference mode)
- Generate new `letter:XX:#color` avoiding rejected ones

**location:**
- Store city/timezone string

### State needed by daemon

Daemon needs a read-only copy of some state for identity decisions:

- `participant_names: dict[str, str]` — to check duplicates, suggest names
- `participant_avatars: dict[str, str]` — to avoid duplicate avatars
- `mode: str` — workshop vs conference
- `debate_phase: str | None` — for late-joiner auto-assign
- `debate_sides: dict[str, str]` — to know side counts for auto-balancing

This state is already synced to daemon on connect via `session_sync` / `state_restore`. The daemon keeps it as a read-only cache and updates it locally when it processes identity requests (so subsequent requests within the same daemon session see consistent state).

### Write-back via WS events

After processing each request, daemon sends a WS event to Railway:

**`participant_registered`** (after set_name):
```json
{
  "type": "participant_registered",
  "participant_id": "abc-123",
  "name": "Alice",
  "avatar": "letter:AL:#4a9",
  "universe": "lotr",
  "score": 0,
  "debate_side": "for"
}
```

`debate_side` is only present if the daemon auto-assigned the participant to a debate side (late joiner during arguments phase). Otherwise omitted.

Railway handler: update `state.participant_names[pid]`, `state.participant_avatars[pid]`, `state.scores[pid]`, etc. If `debate_side` present, update `state.debate_sides[pid]`. Then `broadcast_state()`.

**`participant_location`** (after location):
```json
{
  "type": "participant_location",
  "participant_id": "abc-123",
  "location": "Bucharest, Romania"
}
```

Railway handler: update `state.locations[pid]`. Then `broadcast_participant_update()`.

**`participant_avatar_updated`** (after refresh_avatar):
```json
{
  "type": "participant_avatar_updated",
  "participant_id": "abc-123",
  "avatar": "letter:GA:#e74"
}
```

Railway handler: update `state.participant_avatars[pid]`. Then `broadcast_state()`.

## Daemon: proxy_request Handler

### Threading model

The daemon main loop is synchronous (`drain_queue()` processes handlers on the main thread). Proxy requests must NOT block the main loop — if 50 participants reconnect simultaneously, sequential blocking HTTP calls would stall all other daemon processing (heartbeats, quiz generation, etc.).

**Solution:** Use a `ThreadPoolExecutor` for proxy_request handling. When a `proxy_request` arrives via `drain_queue()`, the handler submits the work to the thread pool and returns immediately. The thread pool worker:

1. Calls daemon's local FastAPI via `httpx` (sync client) at `http://127.0.0.1:{DAEMON_HOST_PORT}`.
2. Sends `participant_registered` (or other state write-back events) over WS.
3. Sends `proxy_response` over WS.

The `DaemonWsClient.send()` is already thread-safe (uses `_ws_lock`), so sending from pool threads is safe.

### New module: `daemon/proxy_handler.py`

```python
_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="proxy")

def handle_proxy_request(data: dict, ws_client: DaemonWsClient):
    """Submit proxy_request to thread pool for non-blocking execution."""
    _executor.submit(_process_proxy_request, data, ws_client)

def _process_proxy_request(data: dict, ws_client: DaemonWsClient):
    """Worker: call local FastAPI, send state events + proxy_response."""
    req_id = data["id"]
    method = data["method"]
    path = data["path"]
    body = data.get("body")
    headers = data.get("headers", {})

    resp = httpx.request(method, f"http://127.0.0.1:{DAEMON_HOST_PORT}{path}",
                         headers=headers, content=body, timeout=10.0)

    ws_client.send({
        "type": "proxy_response",
        "id": req_id,
        "status": resp.status_code,
        "body": resp.text,
        "content_type": resp.headers.get("content-type", "application/json"),
    })
```

### Registration in `daemon/__main__.py`

```python
from daemon.proxy_handler import handle_proxy_request

ws_client.register_handler("proxy_request",
    lambda data: handle_proxy_request(data, ws_client))
```

Note: unlike other handlers that go through `_pending_requests` dict, proxy_request uses a dedicated handler that fires immediately from `drain_queue()` and offloads to the thread pool.

## Participant JS Changes

### `static/participant.js`

Add a helper for participant API calls:

```javascript
function participantApi(path, body) {
    return fetch(`/${sessionId}/api/participant/${path}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Participant-ID': myUuid
        },
        body: JSON.stringify(body)
    });
}
```

Replace WS sends:

| Before | After |
|--------|-------|
| `ws.send(JSON.stringify({type: 'set_name', name: n}))` | `participantApi('name', {name: n})` |
| `ws.send(JSON.stringify({type: 'refresh_avatar'}))` | `participantApi('avatar', {})` |
| `ws.send(JSON.stringify({type: 'location', ...}))` | `participantApi('location', {location: loc})` |

**No changes to WS receive side** — participants still receive state updates via the existing WS connection.

## Backward Compatibility

- Old WS message handlers (`set_name`, `refresh_avatar`, `location`) remain in `features/ws/router.py` during migration.
- Participant JS is switched to REST in a separate commit after the proxy infrastructure is proven.
- Once JS is switched, the old WS handlers can be removed (later phase cleanup).

## Testing Strategy

- **Unit tests** (`tests/daemon/test_participant_router.py`): daemon participant router — name validation, avatar assignment, conference mode, location
- **Unit tests** (`tests/test_proxy_bridge.py`): proxy bridge — Future creation, timeout, correlation matching
- **Integration tests** (`tests/integration/test_rest_proxy.py`): full round-trip — participant REST → Railway → WS → daemon → response + state write-back
- **Existing tests**: must still pass (old WS path unchanged)

## Files Changed

### New files
- `features/ws/proxy_bridge.py` — generic proxy Future/correlation infrastructure + catch-all participant proxy route
- `daemon/participant/__init__.py` — package init
- `daemon/participant/router.py` — identity business logic (moved from WS handler)
- `daemon/proxy_handler.py` — thread pool proxy_request handler
- `tests/daemon/test_participant_router.py` — daemon router unit tests
- `tests/test_proxy_bridge.py` — proxy bridge unit tests
- `tests/integration/test_rest_proxy.py` — end-to-end proxy integration tests

### Modified files
- `features/ws/daemon_protocol.py` — add new message type constants
- `features/ws/router.py` — add `participant_registered`/`participant_location`/`participant_avatar_updated` handlers to `_DAEMON_MSG_HANDLERS`
- `daemon/__main__.py` — register `proxy_request` handler (thread pool)
- `daemon/host_server.py` — mount participant router on daemon FastAPI **before** the catch-all `/api/{path:path}` proxy route (otherwise `/api/participant/*` would be proxied back to Railway, creating an infinite loop)
- `main.py` — mount `participant_proxy_router` on `session_participant` sub-app
- `static/participant.js` — switch identity messages from WS to REST
