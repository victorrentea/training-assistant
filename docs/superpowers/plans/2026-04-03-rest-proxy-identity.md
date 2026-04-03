# Phase 3: REST Proxy + Identity Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a generic REST proxy mechanism on Railway that forwards participant API calls to the daemon over WS, and migrate participant identity logic (set_name, avatar, location) as the first feature.

**Architecture:** Railway receives participant REST calls, wraps them as `proxy_request` WS messages to daemon, awaits a `proxy_response` via asyncio.Future with 5s timeout. Daemon handles proxy requests in a ThreadPoolExecutor, routes them to its local FastAPI participant router, and sends state write-back events (`participant_registered`, etc.) before the proxy response. Railway updates AppState from these events and broadcasts to all clients.

**Tech Stack:** Python 3.12, FastAPI, httpx, websockets, asyncio, concurrent.futures, pytest

**Spec:** `docs/superpowers/specs/2026-04-03-rest-proxy-identity-design.md`

---

## Context

This is **Phase 3** of the railway proxy redesign (`docs/railway-proxy-redesign.md`). Phase 1 (static file sync) and Phase 2 (daemon FastAPI scaffold on localhost:8081) are complete.

Currently, all participant actions go through WebSocket messages handled inline in `features/ws/router.py`. This phase introduces a REST proxy so participant actions can be HTTP calls proxied through Railway to the daemon, where business logic lives.

### What changes

- Railway gets a generic proxy bridge (`features/ws/proxy_bridge.py`) that forwards `/{session_id}/api/participant/*` to daemon via WS
- Daemon gets a participant FastAPI router (`daemon/participant/router.py`) with identity endpoints
- Daemon handles `proxy_request` messages in a thread pool (`daemon/proxy_handler.py`)
- Identity logic (name validation, avatar assignment, conference mode, location) moves from `features/ws/router.py` to daemon
- Daemon sends state write-back events to Railway, which updates AppState and broadcasts
- Participant JS switches identity messages from WS to REST

### What stays the same

- All other participant WS messages (vote, qa, debate, etc.) still handled by Railway
- Old WS handlers for `set_name`, `refresh_avatar`, `location` remain during migration (backward compat)
- Railway remains the AppState owner — daemon writes back via WS events
- Host panel, overlay, daemon WS protocol all unchanged

---

## Design Decisions

### proxy_response resolves Futures directly
The `proxy_response` handler in `_DAEMON_MSG_HANDLERS` is different from other handlers: it does NOT update AppState or trigger broadcasts — it only resolves the pending asyncio.Future. Since it runs on the same event loop as the waiting coroutine, `future.set_result()` is called directly (no `call_soon_threadsafe`).

### Daemon uses ThreadPoolExecutor for proxy requests
The daemon main loop is synchronous. Proxy request handlers must not block `drain_queue()` — otherwise 50 simultaneous reconnects would stall heartbeats, quiz generation, etc. The handler submits work to a `ThreadPoolExecutor(max_workers=8)` and returns immediately. `DaemonWsClient.send()` is already thread-safe.

### Write-back before response
Daemon sends state events (`participant_registered`, etc.) **before** `proxy_response`. Since WS messages are ordered within a connection, Railway processes the state update and broadcasts before the HTTP response reaches the participant.

### Participant router before catch-all
In `daemon/host_server.py`, the participant router must be included **before** the catch-all `/api/{path:path}` proxy route to avoid an infinite loop (daemon → Railway → daemon).

### Catch-all route lives in proxy_bridge.py
No separate `features/participant/` package on Railway — the catch-all route is thin (zero business logic) and colocated with the proxy infrastructure.

---

## File Structure

### Create
- `features/ws/proxy_bridge.py` — Railway: generic proxy Future/correlation + catch-all participant route
- `daemon/proxy_handler.py` — Daemon: thread pool proxy_request handler
- `daemon/participant/__init__.py` — Package init
- `daemon/participant/router.py` — Daemon: identity business logic (set_name, avatar, location)
- `daemon/participant/state.py` — Daemon: local participant state cache
- `tests/test_proxy_bridge.py` — Railway proxy bridge unit tests
- `tests/daemon/test_participant_router.py` — Daemon participant router unit tests

### Modify
- `features/ws/daemon_protocol.py` — Add message type constants
- `features/ws/router.py` — Register `proxy_response` + identity event handlers in `_DAEMON_MSG_HANDLERS`
- `daemon/__main__.py` — Register `proxy_request` handler
- `daemon/host_server.py` — Mount participant router before catch-all
- `main.py` — Mount catch-all participant proxy on `session_participant`
- `static/participant.js` — Switch identity messages from WS to REST

---

## Tasks

### Task 1: Add WS message type constants

**Files:**
- Modify: `features/ws/daemon_protocol.py`

- [ ] **Step 1: Add proxy and identity event constants**

Open `features/ws/daemon_protocol.py`. After the existing outbound message types (around line 44), add:

```python
# --- Proxy (bidirectional) ---
MSG_PROXY_REQUEST = "proxy_request"
MSG_PROXY_RESPONSE = "proxy_response"

# --- Identity events (daemon → backend) ---
MSG_PARTICIPANT_REGISTERED = "participant_registered"
MSG_PARTICIPANT_LOCATION = "participant_location"
MSG_PARTICIPANT_AVATAR_UPDATED = "participant_avatar_updated"
```

- [ ] **Step 2: Run existing tests**

Run: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load -x`
Expected: All pass (no behavior change, just new constants)

- [ ] **Step 3: Commit**

```bash
git add features/ws/daemon_protocol.py
git commit -m "feat: add proxy and identity WS message type constants"
```

---

### Task 2: Create the Railway proxy bridge

**Files:**
- Create: `features/ws/proxy_bridge.py`
- Test: `tests/test_proxy_bridge.py`

- [ ] **Step 1: Create the proxy bridge module**

Create `features/ws/proxy_bridge.py`:

```python
"""Generic REST proxy bridge: forwards participant HTTP calls to daemon via WS."""
import asyncio
import logging
import uuid as _uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from core.state import state

logger = logging.getLogger(__name__)

# Correlation ID → asyncio.Future for pending proxy requests
_pending_requests: dict[str, asyncio.Future] = {}

# Default timeout for proxy requests (seconds)
PROXY_TIMEOUT = 5.0


async def proxy_to_daemon(method: str, path: str, body: bytes | None,
                          headers: dict, participant_id: str | None) -> Response:
    """Forward a participant REST call to daemon via WS proxy_request/proxy_response."""
    ws = state.daemon_ws
    if ws is None:
        return JSONResponse({"error": "Trainer not connected"}, status_code=503)

    req_id = _uuid.uuid4().hex
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _pending_requests[req_id] = future

    # Build proxy_request message
    msg = {
        "type": "proxy_request",
        "id": req_id,
        "method": method,
        "path": path,
        "body": body.decode("utf-8", errors="replace") if body else None,
        "headers": {k: v for k, v in headers.items()
                    if k.lower() not in ("host", "content-length")},
        "participant_id": participant_id,
    }

    try:
        await ws.send_json(msg)
    except Exception:
        _pending_requests.pop(req_id, None)
        return JSONResponse({"error": "Trainer not connected"}, status_code=503)

    try:
        result = await asyncio.wait_for(future, timeout=PROXY_TIMEOUT)
    except asyncio.TimeoutError:
        _pending_requests.pop(req_id, None)
        logger.warning("Proxy request timed out: %s %s", method, path)
        return JSONResponse({"error": "Trainer not responding"}, status_code=503)

    _pending_requests.pop(req_id, None)

    return Response(
        content=result.get("body", ""),
        status_code=result.get("status", 500),
        media_type=result.get("content_type", "application/json"),
    )


async def handle_proxy_response(data: dict):
    """Handle proxy_response from daemon — resolve the pending Future."""
    req_id = data.get("id")
    if not req_id:
        logger.warning("proxy_response missing 'id' field")
        return
    future = _pending_requests.get(req_id)
    if future is None:
        logger.warning("proxy_response for unknown/expired id: %s", req_id)
        return
    if not future.done():
        future.set_result(data)


# ── Catch-all participant proxy route ──

participant_proxy_router = APIRouter()


@participant_proxy_router.api_route(
    "/api/participant/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def participant_proxy(request: Request, path: str):
    """Forward all /api/participant/* calls to daemon via WS proxy."""
    participant_id = request.headers.get("x-participant-id")
    return await proxy_to_daemon(
        method=request.method,
        path=f"/api/participant/{path}",
        body=await request.body(),
        headers=dict(request.headers),
        participant_id=participant_id,
    )
```

- [ ] **Step 2: Write unit tests**

Create `tests/test_proxy_bridge.py`:

```python
"""Tests for the Railway proxy bridge."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from features.ws.proxy_bridge import (
    proxy_to_daemon,
    handle_proxy_response,
    _pending_requests,
)


@pytest.fixture(autouse=True)
def clear_pending():
    """Ensure no leftover pending requests between tests."""
    _pending_requests.clear()
    yield
    _pending_requests.clear()


class TestProxyToDaemon:
    @pytest.mark.asyncio
    async def test_returns_503_when_daemon_disconnected(self):
        with patch("features.ws.proxy_bridge.state") as mock_state:
            mock_state.daemon_ws = None
            resp = await proxy_to_daemon("POST", "/api/participant/name", b'{"name":"Alice"}', {}, "uuid1")
            assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_sends_proxy_request_and_resolves_response(self):
        mock_ws = AsyncMock()

        async def fake_send_json(msg):
            # Simulate daemon responding immediately
            req_id = msg["id"]
            await handle_proxy_response({
                "id": req_id,
                "status": 200,
                "body": '{"ok": true}',
                "content_type": "application/json",
            })

        mock_ws.send_json = fake_send_json

        with patch("features.ws.proxy_bridge.state") as mock_state:
            mock_state.daemon_ws = mock_ws
            resp = await proxy_to_daemon("POST", "/api/participant/name", b'{"name":"Alice"}',
                                         {"x-participant-id": "uuid1"}, "uuid1")
            assert resp.status_code == 200
            assert b"ok" in resp.body

    @pytest.mark.asyncio
    async def test_returns_503_on_timeout(self):
        mock_ws = AsyncMock()
        # send_json succeeds but no response ever comes

        with patch("features.ws.proxy_bridge.state") as mock_state, \
             patch("features.ws.proxy_bridge.PROXY_TIMEOUT", 0.1):
            mock_state.daemon_ws = mock_ws
            resp = await proxy_to_daemon("POST", "/api/participant/name", b'{}', {}, "uuid1")
            assert resp.status_code == 503


class TestHandleProxyResponse:
    @pytest.mark.asyncio
    async def test_resolves_matching_future(self):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        _pending_requests["abc123"] = future
        await handle_proxy_response({"id": "abc123", "status": 200, "body": "ok"})
        assert future.done()
        assert future.result()["status"] == 200

    @pytest.mark.asyncio
    async def test_ignores_unknown_id(self):
        # Should not raise
        await handle_proxy_response({"id": "unknown", "status": 200})

    @pytest.mark.asyncio
    async def test_ignores_missing_id(self):
        # Should not raise
        await handle_proxy_response({"status": 200})
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_proxy_bridge.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add features/ws/proxy_bridge.py tests/test_proxy_bridge.py
git commit -m "feat: add generic REST proxy bridge for participant calls to daemon"
```

---

### Task 3: Register proxy_response and identity event handlers on Railway

**Files:**
- Modify: `features/ws/router.py`

- [ ] **Step 1: Import the new constants and handler**

At the top of `features/ws/router.py`, add to the imports from `daemon_protocol`:

```python
from features.ws.daemon_protocol import (
    # ... existing imports ...
    MSG_PROXY_RESPONSE,
    MSG_PARTICIPANT_REGISTERED,
    MSG_PARTICIPANT_LOCATION,
    MSG_PARTICIPANT_AVATAR_UPDATED,
)
from features.ws.proxy_bridge import handle_proxy_response
```

- [ ] **Step 2: Create identity event handler functions**

Add these handler functions before `_DAEMON_MSG_HANDLERS` (around line 550):

```python
async def _handle_participant_registered(data: dict):
    """Daemon registered a participant — update state and broadcast."""
    pid = data.get("participant_id")
    if not pid:
        return
    state.participant_history.add(pid)
    if "name" in data:
        state.participant_names[pid] = data["name"]
    if "avatar" in data:
        state.participant_avatars[pid] = data["avatar"]
    if "universe" in data:
        state.participant_universes[pid] = data["universe"]
    if "score" in data:
        state.scores.setdefault(pid, data["score"])
        state.base_scores.setdefault(pid, 0)
    if "debate_side" in data and data["debate_side"]:
        state.debate_sides[pid] = data["debate_side"]
        state.debate_auto_assigned.add(pid)
    # Send full state to this participant if connected
    ws = state.participants.get(pid)
    if ws:
        try:
            await send_state_to_participant(ws, pid)
        except Exception:
            pass
    await broadcast_participant_update()
    if state.debate_phase:
        await broadcast_state()


async def _handle_participant_location(data: dict):
    """Daemon set participant location."""
    pid = data.get("participant_id")
    loc = data.get("location")
    if pid and loc:
        state.locations[pid] = loc
        await broadcast_participant_update()


async def _handle_participant_avatar_updated(data: dict):
    """Daemon refreshed participant avatar."""
    pid = data.get("participant_id")
    avatar = data.get("avatar")
    if pid and avatar:
        state.participant_avatars[pid] = avatar
        await broadcast_state()
```

- [ ] **Step 3: Add entries to `_DAEMON_MSG_HANDLERS`**

Add to the `_DAEMON_MSG_HANDLERS` dict (around line 555):

```python
    MSG_PROXY_RESPONSE: handle_proxy_response,
    MSG_PARTICIPANT_REGISTERED: _handle_participant_registered,
    MSG_PARTICIPANT_LOCATION: _handle_participant_location,
    MSG_PARTICIPANT_AVATAR_UPDATED: _handle_participant_avatar_updated,
```

- [ ] **Step 4: Run existing tests**

Run: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load -x`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add features/ws/router.py
git commit -m "feat: register proxy_response and identity event handlers on Railway"
```

---

### Task 4: Mount participant proxy route on Railway

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Import and mount the proxy router**

In `main.py`, add the import near the other router imports:

```python
from features.ws.proxy_bridge import participant_proxy_router
```

Then add to `session_participant` includes (around line 222, before `app.include_router(session_participant)`):

```python
session_participant.include_router(participant_proxy_router)  # /api/participant/* → daemon proxy
```

- [ ] **Step 2: Run existing tests**

Run: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load -x`
Expected: All pass

- [ ] **Step 3: Regenerate openapi.json**

Since we added new routes, regenerate the OpenAPI spec:

Run: `python3 -c "from main import app; import json; json.dump(app.openapi(), open('openapi.json','w'), indent=2)"`

- [ ] **Step 4: Commit**

```bash
git add main.py openapi.json
git commit -m "feat: mount participant proxy route on Railway session_participant"
```

---

### Task 5: Create daemon participant state cache

**Files:**
- Create: `daemon/participant/__init__.py`
- Create: `daemon/participant/state.py`

- [ ] **Step 1: Create the package and state module**

Create `daemon/participant/__init__.py` (empty file).

Create `daemon/participant/state.py`:

```python
"""Local participant state cache for daemon identity logic.

This is a read-only cache of Railway's AppState participant fields,
updated locally when the daemon processes identity requests.
Initial data comes from session_sync/state_restore on WS connect.
"""
import threading


class ParticipantState:
    """Participant state cache for daemon identity logic.

    Thread safety: The router endpoints (async def) run on uvicorn's event loop
    (single-threaded), so concurrent proxy requests are serialized at await points.
    The _lock is only needed for sync_from_restore() which runs on the main thread
    while router handlers may be running on the uvicorn thread.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.participant_names: dict[str, str] = {}
        self.participant_avatars: dict[str, str] = {}
        self.participant_universes: dict[str, str] = {}
        self.scores: dict[str, int] = {}
        self.locations: dict[str, str] = {}
        self.mode: str = "workshop"
        self.debate_phase: str | None = None
        self.debate_sides: dict[str, str] = {}

    def sync_from_restore(self, data: dict):
        """Update cache from state_restore or session_sync data."""
        with self._lock:
            if "participant_names" in data:
                self.participant_names = dict(data["participant_names"])
            if "participant_avatars" in data:
                self.participant_avatars = dict(data["participant_avatars"])
            if "participant_universes" in data:
                self.participant_universes = dict(data["participant_universes"])
            if "scores" in data:
                self.scores = dict(data["scores"])
            if "locations" in data:
                self.locations = dict(data["locations"])
            if "mode" in data:
                self.mode = data["mode"]
            if "debate_phase" in data:
                self.debate_phase = data["debate_phase"]
            if "debate_sides" in data:
                self.debate_sides = dict(data["debate_sides"])

    def snapshot(self) -> dict:
        """Return a copy of all state (for testing/debugging)."""
        with self._lock:
            return {
                "participant_names": dict(self.participant_names),
                "participant_avatars": dict(self.participant_avatars),
                "participant_universes": dict(self.participant_universes),
                "scores": dict(self.scores),
                "locations": dict(self.locations),
                "mode": self.mode,
                "debate_phase": self.debate_phase,
                "debate_sides": dict(self.debate_sides),
            }


# Module-level singleton
participant_state = ParticipantState()
```

- [ ] **Step 2: Run existing tests**

Run: `pytest tests/daemon/ -q --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add daemon/participant/__init__.py daemon/participant/state.py
git commit -m "feat(daemon): add participant state cache for identity logic"
```

---

### Task 6: Create daemon participant router

**Files:**
- Create: `daemon/participant/router.py`
- Test: `tests/daemon/test_participant_router.py`

- [ ] **Step 1: Create the participant router**

Create `daemon/participant/router.py`:

```python
"""Daemon participant router — identity endpoints (set_name, avatar, location)."""
import logging
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from types import SimpleNamespace

from core.names import assign_conference_name
from core.state import assign_avatar, refresh_avatar as _refresh_avatar_logic, LOTR_NAMES
from daemon.participant.state import participant_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/participant", tags=["participant"])


def _build_mini_state() -> SimpleNamespace:
    """Build an AppState-like facade from our local cache for avatar/name functions.

    The core.state functions (assign_avatar, refresh_avatar, assign_conference_name)
    expect an object with participant_names, participant_avatars, participants, etc.
    We use SimpleNamespace to avoid depending on AppState.__init__.

    Note: `participants` is populated from `participant_names.keys()` so that
    assign_conference_name() correctly sees all known participants (it uses
    `state.participants` to determine which names are in use).
    """
    ps = participant_state
    return SimpleNamespace(
        participant_names=ps.participant_names,
        participant_avatars=ps.participant_avatars,
        participant_universes=ps.participant_universes,
        participants={uid: None for uid in ps.participant_names},  # fake WS entries for name pool checks
        mode=ps.mode,
    )


@router.post("/name")
async def set_name(request: Request):
    """Register or rename a participant."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    raw_name = str(body.get("name", "")).strip()[:32]

    ps = participant_state

    # Returning participant — fast path (matches Railway WS behavior: any set_name
    # from a known UUID restores existing identity without re-validation)
    if pid in ps.participant_names:
        return JSONResponse({
            "ok": True,
            "returning": True,
            "name": ps.participant_names[pid],
            "avatar": ps.participant_avatars.get(pid, ""),
        })

    # Conference mode with empty name → auto-assign character name
    if ps.mode == "conference" and not raw_name:
        fake_state = _build_mini_state()
        char_name, universe = assign_conference_name(fake_state)
        raw_name = char_name
        ps.participant_universes[pid] = universe

    if not raw_name:
        return JSONResponse({"error": "Name required"}, status_code=400)

    # Check for duplicate names (race guard)
    taken = {v for k, v in ps.participant_names.items() if k != pid}
    if raw_name in taken:
        # Try to suggest alternative
        available = [n for n in LOTR_NAMES if n not in taken]
        raw_name = available[0] if available else f"Guest{secrets.randbelow(900) + 100}"

    ps.participant_names[pid] = raw_name

    # Assign avatar
    fake_state = _build_mini_state()
    avatar = assign_avatar(fake_state, pid, raw_name)
    # Sync back to our cache
    ps.participant_avatars[pid] = avatar

    # Initialize score
    ps.scores.setdefault(pid, 0)

    # Debate late-joiner auto-assign
    debate_side = None
    if (ps.debate_phase
            and ps.debate_phase != "side_selection"
            and pid not in ps.debate_sides):
        for_count = sum(1 for s in ps.debate_sides.values() if s == "for")
        against_count = sum(1 for s in ps.debate_sides.values() if s == "against")
        side = "for" if for_count <= against_count else "against"
        ps.debate_sides[pid] = side
        debate_side = side
        logger.info("Late joiner %s auto-assigned to %s", raw_name, side)

    # Build write-back event (sent by proxy_handler BEFORE proxy_response)
    request.state.write_back_events = [{
        "type": "participant_registered",
        "participant_id": pid,
        "name": raw_name,
        "avatar": avatar,
        "universe": ps.participant_universes.get(pid, ""),
        "score": ps.scores.get(pid, 0),
        "debate_side": debate_side,
    }]

    return JSONResponse({"ok": True, "name": raw_name, "avatar": avatar})


@router.post("/avatar")
async def refresh_avatar_endpoint(request: Request):
    """Re-roll avatar (conference mode only)."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    rejected = set(body.get("rejected", []))

    fake_state = _build_mini_state()
    new_avatar = _refresh_avatar_logic(fake_state, pid, rejected)

    if not new_avatar:
        return JSONResponse({"error": "No avatar available"}, status_code=409)

    # Sync back to cache
    participant_state.participant_avatars[pid] = new_avatar

    request.state.write_back_events = [{
        "type": "participant_avatar_updated",
        "participant_id": pid,
        "avatar": new_avatar,
    }]

    return JSONResponse({"ok": True, "avatar": new_avatar})


@router.post("/location")
async def set_location(request: Request):
    """Store participant city/timezone."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    loc = str(body.get("location", "")).strip()[:80]
    if not loc:
        return JSONResponse({"error": "Location required"}, status_code=400)

    participant_state.locations[pid] = loc

    request.state.write_back_events = [{
        "type": "participant_location",
        "participant_id": pid,
        "location": loc,
    }]

    return JSONResponse({"ok": True})
```

**Important design note:** The router stores write-back events on `request.state.write_back_events`. The proxy handler reads these after calling the local FastAPI and sends them over WS before `proxy_response`. This keeps the router pure (returns HTTP responses) while allowing state synchronization.

- [ ] **Step 2: Write unit tests**

Create `tests/daemon/test_participant_router.py`:

```python
"""Tests for daemon participant router."""
import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
from fastapi import FastAPI

from daemon.participant.router import router
from daemon.participant.state import ParticipantState


@pytest.fixture
def fresh_state():
    """Provide a clean ParticipantState for each test."""
    ps = ParticipantState()
    ps.mode = "workshop"
    with patch("daemon.participant.router.participant_state", ps):
        yield ps


@pytest.fixture
def client(fresh_state):
    """TestClient with participant router mounted."""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestSetName:
    def test_new_participant_gets_name_and_avatar(self, client, fresh_state):
        resp = client.post("/api/participant/name",
                           json={"name": "Alice"},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["name"] == "Alice"
        assert data["avatar"]  # non-empty
        assert fresh_state.participant_names["uuid1"] == "Alice"

    def test_returning_participant_fast_path(self, client, fresh_state):
        fresh_state.participant_names["uuid1"] = "Bob"
        fresh_state.participant_avatars["uuid1"] = "gandalf.png"
        resp = client.post("/api/participant/name",
                           json={"name": ""},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["returning"] is True
        assert data["name"] == "Bob"

    def test_duplicate_name_gets_alternative(self, client, fresh_state):
        fresh_state.participant_names["other"] = "Alice"
        resp = client.post("/api/participant/name",
                           json={"name": "Alice"},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] != "Alice"  # got an alternative

    def test_empty_name_rejected_in_workshop_mode(self, client, fresh_state):
        resp = client.post("/api/participant/name",
                           json={"name": ""},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400

    def test_conference_mode_auto_assigns_name(self, client, fresh_state):
        fresh_state.mode = "conference"
        resp = client.post("/api/participant/name",
                           json={"name": ""},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"]  # non-empty auto-assigned name

    def test_debate_late_joiner_auto_assigned(self, client, fresh_state):
        fresh_state.debate_phase = "arguments"
        fresh_state.debate_sides = {"a": "for", "b": "for"}
        resp = client.post("/api/participant/name",
                           json={"name": "Charlie"},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        assert fresh_state.debate_sides["uuid1"] == "against"  # fewer against

    def test_missing_participant_id_returns_400(self, client):
        resp = client.post("/api/participant/name", json={"name": "Alice"})
        assert resp.status_code == 400

    def test_name_truncated_to_32_chars(self, client, fresh_state):
        long_name = "A" * 50
        resp = client.post("/api/participant/name",
                           json={"name": long_name},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        assert len(fresh_state.participant_names["uuid1"]) <= 32


class TestRefreshAvatar:
    def test_refresh_returns_new_avatar(self, client, fresh_state):
        fresh_state.participant_avatars["uuid1"] = "gandalf.png"
        resp = client.post("/api/participant/avatar",
                           json={"rejected": []},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["avatar"] != "gandalf.png"


class TestSetLocation:
    def test_location_stored(self, client, fresh_state):
        resp = client.post("/api/participant/location",
                           json={"location": "Bucharest, Romania"},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        assert fresh_state.locations["uuid1"] == "Bucharest, Romania"

    def test_empty_location_rejected(self, client, fresh_state):
        resp = client.post("/api/participant/location",
                           json={"location": ""},
                           headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/daemon/test_participant_router.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add daemon/participant/router.py tests/daemon/test_participant_router.py
git commit -m "feat(daemon): add participant router with identity endpoints"
```

---

### Task 7: Create daemon proxy_request handler + mount participant router

**Files:**
- Create: `daemon/proxy_handler.py`
- Modify: `daemon/host_server.py`
- Modify: `daemon/__main__.py`

- [ ] **Step 1: Create the proxy handler module**

Create `daemon/proxy_handler.py`:

```python
"""Thread pool handler for proxy_request messages from Railway."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor

import httpx

from daemon.config import DAEMON_HOST_PORT

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="proxy")


def handle_proxy_request(data: dict, ws_client):
    """Submit proxy_request to thread pool for non-blocking execution.

    Called from drain_queue() on the main thread — must return immediately.
    """
    _executor.submit(_process_proxy_request, data, ws_client)


def _process_proxy_request(data: dict, ws_client):
    """Worker thread: call local FastAPI, send write-back events + proxy_response."""
    req_id = data.get("id")
    method = data.get("method", "GET")
    path = data.get("path", "/")
    body = data.get("body")
    headers = data.get("headers", {})

    url = f"http://127.0.0.1:{DAEMON_HOST_PORT}{path}"

    try:
        resp = httpx.request(
            method=method,
            url=url,
            headers=headers,
            content=body.encode("utf-8") if body else None,
            timeout=10.0,
        )
    except Exception as e:
        logger.error("Proxy request failed: %s %s — %s", method, path, e)
        ws_client.send({
            "type": "proxy_response",
            "id": req_id,
            "status": 502,
            "body": json.dumps({"error": "Daemon internal error"}),
            "content_type": "application/json",
        })
        return

    # Extract write-back events from response headers (set by daemon participant router)
    # The participant router stores events in a custom header for the proxy handler to read
    write_back_raw = resp.headers.get("x-write-back-events")
    if write_back_raw:
        try:
            events = json.loads(write_back_raw)
            for event in events:
                ws_client.send(event)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse write-back events")

    # Send proxy_response AFTER write-back events
    ws_client.send({
        "type": "proxy_response",
        "id": req_id,
        "status": resp.status_code,
        "body": resp.text,
        "content_type": resp.headers.get("content-type", "application/json"),
    })
```

The write-back events mechanism: the participant router stores events on `request.state.write_back_events`. A middleware on the daemon host server serializes these into an `X-Write-Back-Events` response header. The proxy handler reads this header from the httpx response.

- [ ] **Step 2: Restructure daemon/host_server.py**

The `create_app()` function in `daemon/host_server.py` needs restructuring. The participant router and write-back middleware must be added BEFORE the catch-all `/api/{path:path}` route. Since the catch-all is defined via `@app.api_route` decorator (which registers at definition time), we need to restructure the function so the participant router is included first.

Replace the entire `create_app()` function body (after the lifespan context manager) with this order:

```python
    import json as _json
    from daemon.participant.router import router as participant_router

    app = FastAPI(title="Daemon Host Panel", docs_url=None, redoc_url=None, lifespan=lifespan)

    # --- Write-back middleware (must be first) ---
    @app.middleware("http")
    async def write_back_middleware(request: Request, call_next):
        request.state.write_back_events = []
        response = await call_next(request)
        events = getattr(request.state, "write_back_events", [])
        if events:
            response.headers["X-Write-Back-Events"] = _json.dumps(events)
        return response

    # --- Host HTML page ---
    @app.get("/host/{session_id}")
    async def serve_host_page(session_id: str):
        # ... unchanged ...

    @app.get("/host")
    async def serve_host_page_no_session():
        # ... unchanged ...

    # --- Participant identity endpoints (local, NOT proxied to Railway) ---
    app.include_router(participant_router)

    # --- WebSocket proxy ---
    @app.websocket("/ws/{path:path}")
    async def ws_proxy(websocket: WebSocket, path: str):
        await proxy_websocket(websocket, path, ws_url)

    # --- API reverse proxy (MUST come AFTER participant router to avoid infinite loop) ---
    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
    async def api_proxy(request: Request, path: str):
        return await proxy_http(request, f"api/{path}", http_client)

    # --- Static files (mounted last) ---
    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    return app
```

**Critical ordering:** `app.include_router(participant_router)` BEFORE `@app.api_route("/api/{path:path}")`. Otherwise `/api/participant/name` would be caught by the catch-all and proxied to Railway, which proxies back to daemon → infinite loop.

- [ ] **Step 3: Register proxy_request handler in daemon/__main__.py**

In `daemon/__main__.py`, add after the other handler registrations (around line 330):

```python
from daemon.proxy_handler import handle_proxy_request

ws_client.register_handler("proxy_request",
    lambda data: handle_proxy_request(data, ws_client))
```

Note: this does NOT use the `_ws_handler` pattern (which stores in `_pending_requests` dict for main-loop processing). Instead it directly submits to the thread pool.

- [ ] **Step 4: Run existing daemon tests**

Run: `pytest tests/daemon/ -q --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add daemon/proxy_handler.py daemon/host_server.py daemon/__main__.py
git commit -m "feat(daemon): add proxy_request handler, write-back middleware, mount participant router"
```

---

### Task 8: Switch participant JS from WS to REST for identity

**Files:**
- Modify: `static/participant.js`

- [ ] **Step 1: Read current participant.js to find the identity WS sends**

Read `static/participant.js` and locate:
- The `ws.send(JSON.stringify({type: 'set_name', ...}))` calls
- The `ws.send(JSON.stringify({type: 'refresh_avatar', ...}))` calls
- The `ws.send(JSON.stringify({type: 'location', ...}))` calls
- The `sessionId` variable (needed for URL prefix)
- The `myUuid` variable (the participant UUID)

- [ ] **Step 2: Add participantApi helper function**

Add near the top of the JS file (after `myUuid` is defined):

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

- [ ] **Step 3: Replace set_name WS send with REST call**

Find all `ws.send(JSON.stringify({type: 'set_name'...}))` and replace with:
```javascript
participantApi('name', {name: nameValue})
```

The response is not awaited — the state update comes via the existing WS broadcast.

- [ ] **Step 4: Replace refresh_avatar WS send with REST call**

Find `ws.send(JSON.stringify({type: 'refresh_avatar'...}))` and replace with:
```javascript
participantApi('avatar', {rejected: rejectedList})
```

- [ ] **Step 5: Replace location WS send with REST call**

Find `ws.send(JSON.stringify({type: 'location'...}))` and replace with:
```javascript
participantApi('location', {location: locationString})
```

- [ ] **Step 6: Run existing tests**

Run: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load -x`
Expected: All pass (old WS handlers still exist on Railway, both paths work)

- [ ] **Step 7: Commit**

```bash
git add static/participant.js
git commit -m "feat: switch participant identity messages from WS to REST"
```

---

### Task 9: Integration test — full proxy round-trip

**Files:**
- Create: `tests/integration/test_rest_proxy.py`

- [ ] **Step 1: Write integration test**

Create `tests/integration/test_rest_proxy.py`:

```python
"""Integration tests for REST proxy: participant → Railway → daemon → response."""
import json
import os
import time
import base64

import pytest
import requests
from websockets.sync.client import connect as ws_connect


def _daemon_ws_url(server_url: str) -> str:
    return server_url.replace("http://", "ws://") + "/ws/daemon"


def _auth_headers() -> dict:
    user = os.environ.get("HOST_USERNAME", "host")
    pw = os.environ.get("HOST_PASSWORD", "testpass")
    creds = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


class TestRestProxy:
    """Test the REST proxy chain: participant REST → Railway → daemon WS → response."""

    def test_participant_name_via_proxy(self, server_url, session_id):
        """POST /api/participant/name is proxied to daemon and returns success."""
        # Connect daemon WS so proxy has a target
        with ws_connect(_daemon_ws_url(server_url), additional_headers=_auth_headers()) as ws:
            # Drain initial messages
            time.sleep(0.3)
            while True:
                try:
                    ws.recv(timeout=0.1)
                except Exception:
                    break

            # Make participant REST call
            resp = requests.post(
                f"{server_url}/{session_id}/api/participant/name",
                json={"name": "TestProxy"},
                headers={"X-Participant-ID": "proxy-test-uuid"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("ok") is True
            assert data.get("name") == "TestProxy"

    def test_proxy_returns_503_without_daemon(self, server_url, session_id):
        """Without daemon connected, proxy returns 503."""
        resp = requests.post(
            f"{server_url}/{session_id}/api/participant/name",
            json={"name": "NoBody"},
            headers={"X-Participant-ID": "no-daemon-uuid"},
        )
        assert resp.status_code == 503
```

**Note:** The integration test `test_participant_name_via_proxy` requires the daemon to be running with the participant router. This test may need to be marked as `nightly` or adjusted depending on the test infrastructure. If the integration test server doesn't have a daemon connected, only `test_proxy_returns_503_without_daemon` will work as a reliable CI test.

- [ ] **Step 2: Run the test**

Run: `pytest tests/integration/test_rest_proxy.py -v -k "503"`
Expected: `test_proxy_returns_503_without_daemon` passes (no daemon needed)

The full proxy round-trip test requires a daemon with the participant router running. If the integration test infrastructure supports it:
Run: `pytest tests/integration/test_rest_proxy.py -v`

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_rest_proxy.py
git commit -m "test: add integration tests for REST proxy round-trip"
```

---

## Verification

After all tasks complete:

1. **Unit tests**: `pytest tests/test_proxy_bridge.py tests/daemon/test_participant_router.py -v` — all pass
2. **Daemon tests**: `pytest tests/daemon/ -q --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript` — all pass
3. **Full test suite**: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load` — all pass
4. **Manual test**:
   - Start Railway backend: `python3 -m uvicorn main:app --port 8000`
   - Start daemon: `python3 -m daemon`
   - Open participant page, enter name → should work via REST proxy (check browser network tab: POST to `/api/participant/name`)
   - Old WS path should also still work (backward compat)

---

## Summary

| Task | Description | Complexity | Changes |
|------|-------------|------------|---------|
| 1 | WS message type constants | Small | Railway |
| 2 | Railway proxy bridge + tests | Medium | Railway |
| 3 | Register proxy_response + identity handlers | Medium | Railway |
| 4 | Mount proxy route on session_participant | Small | Railway |
| 5 | Daemon participant state cache | Small | Daemon |
| 6 | Daemon participant router + tests | Large | Daemon |
| 7 | Proxy handler + write-back middleware + mount router | Medium | Daemon |
| 8 | Switch participant JS to REST | Medium | Frontend |
| 9 | Integration test | Small | Tests |
