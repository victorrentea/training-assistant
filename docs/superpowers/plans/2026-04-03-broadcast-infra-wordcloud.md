# Phase 4a: Broadcast Infrastructure + Word Cloud Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build generic daemon→participant broadcast infrastructure on Railway, and migrate word cloud end-to-end (state, endpoints, broadcasts) to the daemon as the first proof of the pattern.

**Architecture:** Daemon sends `{type: "broadcast", event: {...}}` over the daemon WS. Railway extracts the inner event and fans it out to all connected participant WSs unchanged. Word cloud state lives on daemon; participant word submissions go via the Phase 3 REST proxy; host topic/clear/word calls hit daemon localhost directly. Railway AppState is kept in sync via write-back events for backward compatibility.

**Tech Stack:** Python 3.12, FastAPI, httpx, websockets, asyncio, pytest

**Spec:** `docs/superpowers/specs/2026-04-03-broadcast-infra-wordcloud-design.md`

---

## Context

Phase 3 (REST proxy + identity migration) is complete. Railway has a generic proxy bridge (`features/ws/proxy_bridge.py`) that forwards `/{session_id}/api/participant/*` REST calls to the daemon via WS `proxy_request`/`proxy_response`. The daemon has a `ThreadPoolExecutor`-based proxy handler (`daemon/proxy_handler.py`) that calls its local FastAPI and sends write-back events via the `X-Write-Back-Events` response header.

### What changes

- Railway gets a generic broadcast fan-out handler for `MSG_BROADCAST` (daemon→participants)
- Railway gets state sync handlers for `wordcloud_state_sync` and `score_award`
- Railway pushes current state to daemon on WS connect (`daemon_state_push`)
- Daemon gets a word cloud state cache + router (participant + host endpoints)
- Daemon sends broadcast events and write-back events after word cloud mutations
- Participant JS switches `wordcloud_word` from WS to REST
- Host JS switches `wordcloud_word` from WS to REST (via localhost)

### What stays the same

- All other participant WS messages (vote, qa, debate, etc.) handled by Railway
- Old WS `wordcloud_word` handler stays in Railway for backward compat
- Railway word cloud endpoints (`features/wordcloud/router.py`) stay as dead code for now
- Host topic/clear JS calls unchanged (already call `/api/wordcloud/*`)

---

## Design Decisions

### State push on daemon connect
Railway currently sends only `sync_files` on daemon WS connect. The daemon has no way to receive Railway's current AppState. This plan adds a `daemon_state_push` message sent by Railway right after `sync_files`, containing the fields the daemon needs: participant names/avatars/universes/scores/locations, mode, debate state, current_activity, and word cloud state. The daemon handlers (`ParticipantState.sync_from_restore()` and `WordCloudState.sync_from_restore()`) consume this on the daemon's main thread via `drain_queue()`.

### Two transport mechanisms for WS events
- **Participant-proxied calls:** Write-back events in `request.state.write_back_events` → `X-Write-Back-Events` header → `proxy_handler` reads and sends over WS.
- **Host-direct calls:** `_ws_client.send()` called directly from the router. `DaemonWsClient.send()` is a fast sync call (json.dumps + ws.send under a lock) — acceptable in async context without `run_in_executor`.

### Score award is transitional
`score_award` write-back triggers `broadcast_state()` on Railway — a full personalized state dump. This is redundant with the `wordcloud_updated` broadcast but needed because `my_score` is only delivered via state dumps. Accepted as transitional until scoring migrates to daemon.

---

## File Structure

### Create
- `daemon/wordcloud/__init__.py` — package init
- `daemon/wordcloud/state.py` — `WordCloudState` singleton
- `daemon/wordcloud/router.py` — participant + host word cloud endpoints
- `tests/daemon/test_wordcloud_router.py` — daemon router unit tests
- `tests/test_broadcast_handler.py` — Railway broadcast handler unit tests

### Modify
- `features/ws/daemon_protocol.py` — add `MSG_BROADCAST`, `MSG_WORDCLOUD_STATE_SYNC`, `MSG_SCORE_AWARD`, `MSG_DAEMON_STATE_PUSH`
- `features/ws/router.py` — add handlers + daemon_state_push on connect
- `daemon/host_server.py` — mount word cloud routers before catch-all
- `daemon/__main__.py` — register `daemon_state_push` handler, set `ws_client` on word cloud router
- `daemon/participant/state.py` — add `current_activity` field
- `static/participant.js` — replace `sendWS('wordcloud_word')` with REST; add `wordcloud_updated` handler
- `static/host.js` — replace `sendWS('wordcloud_word')` with REST

---

## Tasks

### Task 1: Add WS message type constants

**Files:**
- Modify: `features/ws/daemon_protocol.py`

- [ ] **Step 1: Add constants**

Open `features/ws/daemon_protocol.py`. Before the blank line at line 60 (before `async def push_to_daemon`), add:

```python
# --- Generic broadcast (daemon → all participants via backend) ---
MSG_BROADCAST = "broadcast"

# --- Word cloud state sync (daemon → backend) ---
MSG_WORDCLOUD_STATE_SYNC = "wordcloud_state_sync"

# --- Score award (daemon → backend, transitional) ---
MSG_SCORE_AWARD = "score_award"

# --- State push (backend → daemon, on connect) ---
MSG_DAEMON_STATE_PUSH = "daemon_state_push"
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load -x`
Expected: All pass

- [ ] **Step 3: Commit and push**

```bash
git add features/ws/daemon_protocol.py
git commit -m "feat: add broadcast, wordcloud sync, score award, and state push WS constants"
git pull --rebase origin master && git push origin master
```

---

### Task 2: Add Railway broadcast + state sync + score award handlers

**Files:**
- Modify: `features/ws/router.py`
- Create: `tests/test_broadcast_handler.py`

- [ ] **Step 1: Extend imports in `features/ws/router.py`**

At line 44 (inside the `from features.ws.daemon_protocol import (...)` block), add to the imports:

```python
    MSG_BROADCAST,
    MSG_WORDCLOUD_STATE_SYNC,
    MSG_SCORE_AWARD,
```

- [ ] **Step 2: Add handler functions**

Add these three handler functions before `_DAEMON_MSG_HANDLERS` (around line 600):

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


async def _handle_wordcloud_state_sync(data: dict):
    """Keep Railway's AppState word cloud fields in sync with daemon."""
    if "words" in data:
        state.wordcloud_words = data["words"]
    if "word_order" in data:
        state.wordcloud_word_order = data["word_order"]
    if "topic" in data:
        state.wordcloud_topic = data["topic"]


async def _handle_score_award(data: dict):
    """Award points to a participant (daemon → Railway, transitional)."""
    pid = data.get("participant_id")
    points = data.get("points", 0)
    if pid and points:
        state.add_score(pid, points)
        await broadcast_state()
```

- [ ] **Step 3: Register in `_DAEMON_MSG_HANDLERS`**

Add to the `_DAEMON_MSG_HANDLERS` dict (after the existing entries, before the closing `}`):

```python
    MSG_BROADCAST: _handle_broadcast,
    MSG_WORDCLOUD_STATE_SYNC: _handle_wordcloud_state_sync,
    MSG_SCORE_AWARD: _handle_score_award,
```

- [ ] **Step 4: Create broadcast handler tests**

Create `tests/test_broadcast_handler.py`:

```python
"""Tests for the Railway broadcast fan-out handler."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from features.ws.router import _handle_broadcast, _handle_wordcloud_state_sync, _handle_score_award


class TestHandleBroadcast:
    @pytest.mark.anyio
    async def test_fans_out_event_to_participants(self):
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        mock_state = MagicMock()
        mock_state.participants = {"uuid1": ws1, "uuid2": ws2}

        with patch("features.ws.router.state", mock_state):
            await _handle_broadcast({"event": {"type": "wordcloud_updated", "words": {"hello": 1}}})

        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()
        sent = json.loads(ws1.send_text.call_args[0][0])
        assert sent["type"] == "wordcloud_updated"
        assert sent["words"] == {"hello": 1}

    @pytest.mark.anyio
    async def test_skips_host_and_overlay(self):
        participant_ws = AsyncMock()
        host_ws = AsyncMock()
        overlay_ws = AsyncMock()
        mock_state = MagicMock()
        mock_state.participants = {
            "uuid1": participant_ws,
            "__host__": host_ws,
            "__overlay__": overlay_ws,
        }

        with patch("features.ws.router.state", mock_state):
            await _handle_broadcast({"event": {"type": "test"}})

        participant_ws.send_text.assert_called_once()
        host_ws.send_text.assert_not_called()
        overlay_ws.send_text.assert_not_called()

    @pytest.mark.anyio
    async def test_handles_dead_connections(self):
        good_ws = AsyncMock()
        bad_ws = AsyncMock()
        bad_ws.send_text.side_effect = Exception("connection closed")
        mock_state = MagicMock()
        mock_state.participants = {"uuid1": good_ws, "uuid2": bad_ws}

        with patch("features.ws.router.state", mock_state):
            await _handle_broadcast({"event": {"type": "test"}})

        good_ws.send_text.assert_called_once()

    @pytest.mark.anyio
    async def test_ignores_missing_event(self):
        mock_state = MagicMock()
        mock_state.participants = {"uuid1": AsyncMock()}

        with patch("features.ws.router.state", mock_state):
            await _handle_broadcast({})  # no event key

        mock_state.participants["uuid1"].send_text.assert_not_called()


class TestHandleWordcloudStateSync:
    @pytest.mark.anyio
    async def test_updates_appstate(self):
        mock_state = MagicMock()
        with patch("features.ws.router.state", mock_state):
            await _handle_wordcloud_state_sync({
                "words": {"hello": 2},
                "word_order": ["hello"],
                "topic": "greetings",
            })
        assert mock_state.wordcloud_words == {"hello": 2}
        assert mock_state.wordcloud_word_order == ["hello"]
        assert mock_state.wordcloud_topic == "greetings"


class TestHandleScoreAward:
    @pytest.mark.anyio
    async def test_awards_score_and_broadcasts(self):
        mock_state = MagicMock()
        with patch("features.ws.router.state", mock_state), \
             patch("features.ws.router.broadcast_state", new_callable=AsyncMock) as mock_broadcast:
            await _handle_score_award({"participant_id": "uuid1", "points": 200})
        mock_state.add_score.assert_called_once_with("uuid1", 200)
        mock_broadcast.assert_called_once()
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_broadcast_handler.py -v`
Expected: All pass

Run: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load -x`
Expected: All pass

- [ ] **Step 6: Commit and push**

```bash
git add features/ws/router.py tests/test_broadcast_handler.py
git commit -m "feat: add broadcast fan-out, wordcloud state sync, and score award handlers on Railway"
git pull --rebase origin master && git push origin master
```

---

### Task 3: Add daemon_state_push on daemon WS connect

**Files:**
- Modify: `features/ws/router.py`

- [ ] **Step 1: Send state push after sync_files**

First, add `MSG_DAEMON_STATE_PUSH` to the import block at line 44 in `features/ws/router.py` (the `from features.ws.daemon_protocol import (...)` block):

```python
    MSG_DAEMON_STATE_PUSH,
```

Then in `daemon_websocket_endpoint()` (around line 663, after the `sync_files` send), add:

```python
    # Push current state to daemon so it can serve participant/host requests
    try:
        await websocket.send_json({
            "type": MSG_DAEMON_STATE_PUSH,
            "participant_names": state.participant_names,
            "participant_avatars": state.participant_avatars,
            "participant_universes": state.participant_universes,
            "scores": dict(state.scores),
            "locations": dict(state.locations),
            "mode": state.mode,
            "debate_phase": state.debate_phase,
            "debate_sides": dict(state.debate_sides),
            "current_activity": state.current_activity.value if hasattr(state.current_activity, 'value') else str(state.current_activity),
            "wordcloud_words": state.wordcloud_words,
            "wordcloud_word_order": state.wordcloud_word_order,
            "wordcloud_topic": state.wordcloud_topic,
        })
    except Exception:
        logger.warning("Failed to send daemon_state_push")
```

Note: `state.current_activity` is an `ActivityType` enum. Use `.value` to get the string. Check `core/state.py` for the enum definition and whether it has a `.value` attribute.

- [ ] **Step 2: Run tests**

Run: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load -x`
Expected: All pass

- [ ] **Step 3: Commit and push**

```bash
git add features/ws/router.py
git commit -m "feat: push current state to daemon on WS connect (daemon_state_push)"
git pull --rebase origin master && git push origin master
```

---

### Task 4: Add `current_activity` to daemon ParticipantState

**Files:**
- Modify: `daemon/participant/state.py`

- [ ] **Step 1: Add `current_activity` field**

Read `daemon/participant/state.py`. In `ParticipantState.__init__()`, add after `debate_sides`:

```python
        self.current_activity: str = "none"
```

In `sync_from_restore()`, add inside the `with self._lock:` block:

```python
            if "current_activity" in data:
                self.current_activity = str(data["current_activity"])
```

In `snapshot()`, add to the returned dict:

```python
                "current_activity": self.current_activity,
```

- [ ] **Step 2: Run daemon tests**

Run: `pytest tests/daemon/ -q --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript`
Expected: All pass

- [ ] **Step 3: Commit and push**

```bash
git add daemon/participant/state.py
git commit -m "feat(daemon): add current_activity to ParticipantState"
git pull --rebase origin master && git push origin master
```

---

### Task 5: Create daemon word cloud state

**Files:**
- Create: `daemon/wordcloud/__init__.py`
- Create: `daemon/wordcloud/state.py`

- [ ] **Step 1: Create package init**

Create empty file `daemon/wordcloud/__init__.py`.

- [ ] **Step 2: Create state module**

Create `daemon/wordcloud/state.py`:

```python
"""Word cloud state cache for daemon.

Owns the word cloud state (words, word_order, topic).
Initial data comes from daemon_state_push on WS connect.
"""
import threading


class WordCloudState:
    """Word cloud state. Mutation methods run on uvicorn's single-threaded
    event loop (no lock needed). sync_from_restore runs on the main thread
    and uses _lock for cross-thread safety.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.words: dict[str, int] = {}
        self.word_order: list[str] = []  # newest first
        self.topic: str = ""

    def sync_from_restore(self, data: dict):
        """Update from daemon_state_push. Called from main thread."""
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
        """Add a word, return current state for broadcast."""
        word = word.strip().lower()
        if word not in self.words:
            self.word_order.insert(0, word)
        self.words[word] = self.words.get(word, 0) + 1
        return self.snapshot()

    def set_topic(self, topic: str) -> dict:
        """Set topic, return current state for broadcast."""
        self.topic = topic.strip()
        return self.snapshot()

    def clear(self) -> dict:
        """Clear all words and topic, return empty state for broadcast."""
        self.words.clear()
        self.word_order.clear()
        self.topic = ""
        return self.snapshot()

    def snapshot(self) -> dict:
        """Return a copy of current state."""
        return {
            "words": dict(self.words),
            "word_order": list(self.word_order),
            "topic": self.topic,
        }


# Module-level singleton
wordcloud_state = WordCloudState()
```

- [ ] **Step 3: Run daemon tests**

Run: `pytest tests/daemon/ -q --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript`
Expected: All pass

- [ ] **Step 4: Commit and push**

```bash
git add daemon/wordcloud/__init__.py daemon/wordcloud/state.py
git commit -m "feat(daemon): add word cloud state cache"
git pull --rebase origin master && git push origin master
```

---

### Task 6: Create daemon word cloud router + tests

**Files:**
- Create: `daemon/wordcloud/router.py`
- Create: `tests/daemon/test_wordcloud_router.py`

- [ ] **Step 1: Create the router**

Create `daemon/wordcloud/router.py`:

```python
"""Daemon word cloud router — participant + host endpoints."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from daemon.participant.state import participant_state
from daemon.wordcloud.state import wordcloud_state

logger = logging.getLogger(__name__)

# Set by __main__.py during daemon startup
_ws_client = None

# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant/wordcloud", tags=["wordcloud"])


@participant_router.post("/word")
async def submit_word(request: Request):
    """Participant submits a word to the word cloud."""
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


# ── Host router (called directly on daemon localhost) ──
# NOTE: Host JS calls API('/wordcloud/word') which expands to /api/{session_id}/wordcloud/word.
# The prefix includes {session_id} path parameter to match this pattern.

host_router = APIRouter(prefix="/api/{session_id}/wordcloud", tags=["wordcloud"])


@host_router.post("/word")
async def host_submit_word(request: Request):
    """Host submits a word — same as participant but no scoring."""
    body = await request.json()
    word = str(body.get("word", "")).strip()
    if not word or len(word) > 40:
        return JSONResponse({"error": "Invalid word"}, status_code=400)

    snapshot = wordcloud_state.add_word(word)
    _send_wordcloud_events(snapshot)
    return JSONResponse({"ok": True})


@host_router.post("/topic")
async def set_topic(request: Request):
    """Host sets the word cloud topic."""
    body = await request.json()
    topic = str(body.get("topic", "")).strip()
    snapshot = wordcloud_state.set_topic(topic)
    _send_wordcloud_events(snapshot)
    return JSONResponse({"ok": True})


@host_router.post("/clear")
async def clear_wordcloud(request: Request):
    """Host clears the word cloud."""
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

- [ ] **Step 2: Create unit tests**

Create `tests/daemon/test_wordcloud_router.py`:

```python
"""Tests for daemon word cloud router."""
import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
from fastapi import FastAPI

from daemon.wordcloud.router import participant_router, host_router
from daemon.wordcloud.state import WordCloudState
from daemon.participant.state import ParticipantState


@pytest.fixture
def fresh_wc_state():
    """Clean WordCloudState for each test."""
    wcs = WordCloudState()
    with patch("daemon.wordcloud.router.wordcloud_state", wcs):
        yield wcs


@pytest.fixture
def fresh_participant_state():
    """Clean ParticipantState with wordcloud activity."""
    ps = ParticipantState()
    ps.current_activity = "wordcloud"
    with patch("daemon.wordcloud.router.participant_state", ps):
        yield ps


@pytest.fixture
def mock_ws_client():
    """Mock ws_client for host-direct path."""
    mock = MagicMock()
    mock.send.return_value = True
    with patch("daemon.wordcloud.router._ws_client", mock):
        yield mock


@pytest.fixture
def participant_client(fresh_wc_state, fresh_participant_state):
    """TestClient with participant wordcloud router."""
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture
def host_client(fresh_wc_state, mock_ws_client):
    """TestClient with host wordcloud router."""
    app = FastAPI()
    app.include_router(host_router)
    return TestClient(app)


class TestParticipantSubmitWord:
    def test_word_added_and_counted(self, participant_client, fresh_wc_state):
        resp = participant_client.post("/api/participant/wordcloud/word",
                                       json={"word": "Hello"},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        assert fresh_wc_state.words.get("hello") == 1  # lowercased

    def test_duplicate_word_increments(self, participant_client, fresh_wc_state):
        participant_client.post("/api/participant/wordcloud/word",
                                json={"word": "test"},
                                headers={"X-Participant-ID": "uuid1"})
        participant_client.post("/api/participant/wordcloud/word",
                                json={"word": "test"},
                                headers={"X-Participant-ID": "uuid2"})
        assert fresh_wc_state.words.get("test") == 2

    def test_empty_word_rejected(self, participant_client):
        resp = participant_client.post("/api/participant/wordcloud/word",
                                       json={"word": ""},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400

    def test_long_word_rejected(self, participant_client):
        resp = participant_client.post("/api/participant/wordcloud/word",
                                       json={"word": "a" * 41},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400

    def test_missing_participant_id_rejected(self, participant_client):
        resp = participant_client.post("/api/participant/wordcloud/word",
                                       json={"word": "test"})
        assert resp.status_code == 400

    def test_activity_gate_rejects_when_not_wordcloud(self, participant_client, fresh_participant_state):
        fresh_participant_state.current_activity = "poll"
        resp = participant_client.post("/api/participant/wordcloud/word",
                                       json={"word": "test"},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 409

    def test_word_order_newest_first(self, participant_client, fresh_wc_state):
        participant_client.post("/api/participant/wordcloud/word",
                                json={"word": "first"},
                                headers={"X-Participant-ID": "uuid1"})
        participant_client.post("/api/participant/wordcloud/word",
                                json={"word": "second"},
                                headers={"X-Participant-ID": "uuid1"})
        assert fresh_wc_state.word_order[0] == "second"
        assert fresh_wc_state.word_order[1] == "first"


class TestHostEndpoints:
    # Host router prefix is /api/{session_id}/wordcloud — use "test-session" as session_id
    def test_host_word_submission(self, host_client, fresh_wc_state, mock_ws_client):
        resp = host_client.post("/api/test-session/wordcloud/word", json={"word": "Hello"})
        assert resp.status_code == 200
        assert fresh_wc_state.words.get("hello") == 1
        # Verify WS events were sent
        assert mock_ws_client.send.call_count == 2  # broadcast + state_sync

    def test_set_topic(self, host_client, fresh_wc_state, mock_ws_client):
        resp = host_client.post("/api/test-session/wordcloud/topic", json={"topic": "AI trends"})
        assert resp.status_code == 200
        assert fresh_wc_state.topic == "AI trends"
        assert mock_ws_client.send.call_count == 2

    def test_clear(self, host_client, fresh_wc_state, mock_ws_client):
        fresh_wc_state.words = {"hello": 1}
        fresh_wc_state.word_order = ["hello"]
        fresh_wc_state.topic = "test"
        resp = host_client.post("/api/test-session/wordcloud/clear", json={})
        assert resp.status_code == 200
        assert fresh_wc_state.words == {}
        assert fresh_wc_state.word_order == []
        assert fresh_wc_state.topic == ""

    def test_host_word_sends_broadcast_event(self, host_client, mock_ws_client):
        host_client.post("/api/test-session/wordcloud/word", json={"word": "test"})
        broadcast_call = mock_ws_client.send.call_args_list[0]
        msg = broadcast_call[0][0]
        assert msg["type"] == "broadcast"
        assert msg["event"]["type"] == "wordcloud_updated"
        assert msg["event"]["words"] == {"test": 1}
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/daemon/test_wordcloud_router.py -v`
Expected: All pass

- [ ] **Step 4: Commit and push**

```bash
git add daemon/wordcloud/router.py tests/daemon/test_wordcloud_router.py
git commit -m "feat(daemon): add word cloud router with participant + host endpoints"
git pull --rebase origin master && git push origin master
```

---

### Task 7: Mount word cloud routers on daemon + wire state sync

**Files:**
- Modify: `daemon/host_server.py`
- Modify: `daemon/__main__.py`

- [ ] **Step 1: Mount routers in host_server.py**

Read `daemon/host_server.py` and find the `create_app()` function. Add imports and mount word cloud routers BEFORE the catch-all `/api/{path:path}` route but AFTER the participant identity router.

Add import at the top of `create_app()` or at file level:

```python
from daemon.wordcloud.router import participant_router as wc_participant_router
from daemon.wordcloud.router import host_router as wc_host_router
```

Add after line 69 (`app.include_router(participant_router)`):

```python
    app.include_router(wc_participant_router)  # /api/participant/wordcloud/*
    app.include_router(wc_host_router)         # /api/{session_id}/wordcloud/*
```

**Critical:** Both must be BEFORE the catch-all `@app.api_route("/api/{path:path}", ...)`. The host router prefix `/api/{session_id}/wordcloud` includes a path parameter because host JS calls `API('/wordcloud/word')` which expands to `/api/{session_id}/wordcloud/word`.

- [ ] **Step 2: Register daemon_state_push handler and wire ws_client in __main__.py**

Read `daemon/__main__.py` and find where `ws_client.register_handler("proxy_request", ...)` is (around line 331). Add after it:

```python
    # Word cloud ws_client injection
    import daemon.wordcloud.router as wc_router
    wc_router._ws_client = ws_client

    # State push handler — daemon receives current state from Railway on connect
    from daemon.participant.state import participant_state
    from daemon.wordcloud.state import wordcloud_state

    def _handle_daemon_state_push(data):
        participant_state.sync_from_restore(data)
        wordcloud_state.sync_from_restore(data)

    ws_client.register_handler("daemon_state_push", _handle_daemon_state_push)
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/daemon/ -q --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript`
Expected: All pass

Run: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load -x`
Expected: All pass

- [ ] **Step 4: Commit and push**

```bash
git add daemon/host_server.py daemon/__main__.py
git commit -m "feat(daemon): mount word cloud routers, wire state push handler and ws_client"
git pull --rebase origin master && git push origin master
```

---

### Task 8: Switch participant JS from WS to REST for word cloud

**Files:**
- Modify: `static/participant.js`

- [ ] **Step 1: Read participant.js**

Read `static/participant.js` and find:
- The `sendWS('wordcloud_word'` call (around line 3108)
- The `handleMessage` function and its switch statement (around line 2595)

- [ ] **Step 2: Replace WS send with REST call**

Find (around line 3108):
```javascript
sendWS('wordcloud_word', { word });
```

Replace with:
```javascript
participantApi('wordcloud/word', { word });
```

- [ ] **Step 3: Add `wordcloud_updated` event handler**

In the `handleMessage` switch statement, find a suitable place (near other word cloud handling) and add a new case:

```javascript
      case 'wordcloud_updated':
        renderWordCloudScreen(msg.words || {}, msg.word_order || [], msg.topic || '');
        break;
```

Note: The existing code uses `msg.wordcloud_words`, `msg.wordcloud_word_order`, `msg.wordcloud_topic` (from the state dump). The new broadcast event uses shorter field names: `msg.words`, `msg.word_order`, `msg.topic`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load -x`
Expected: All pass

- [ ] **Step 5: Commit and push**

```bash
git add static/participant.js
git commit -m "feat: switch participant word cloud from WS to REST + handle wordcloud_updated broadcast"
git pull --rebase origin master && git push origin master
```

---

### Task 9: Switch host JS word submission to REST

**Files:**
- Modify: `static/host.js`

- [ ] **Step 1: Read host.js**

Read `static/host.js` and find the `sendWS('wordcloud_word'` call (around line 2173).

- [ ] **Step 2: Replace WS send with REST call**

Find:
```javascript
sendWS('wordcloud_word', { word });
```

Replace with:
```javascript
fetch(API('/wordcloud/word'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ word })
});
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load -x`
Expected: All pass

- [ ] **Step 4: Commit and push**

```bash
git add static/host.js
git commit -m "feat: switch host word cloud submission from WS to REST"
git pull --rebase origin master && git push origin master
```

---

## Verification

After all tasks complete:

1. **Unit tests**: `pytest tests/test_broadcast_handler.py tests/daemon/test_wordcloud_router.py -v` — all pass
2. **Daemon tests**: `pytest tests/daemon/ -q --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript` — all pass
3. **Full test suite**: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load` — all pass
4. **Manual test**:
   - Start Railway backend: `python3 -m uvicorn main:app --port 8000`
   - Start daemon: `python3 -m daemon`
   - Open participant page, wait for word cloud activity
   - Type a word → should appear in word cloud via REST proxy + broadcast
   - Open host panel, set topic → participants see topic update
   - Host clears → participants see empty word cloud
   - Check browser network tab: participant sends `POST /api/participant/wordcloud/word` (not WS)

---

## Summary

| Task | Description | Complexity | Changes |
|------|-------------|------------|---------|
| 1 | WS message type constants | Small | Railway |
| 2 | Broadcast + state sync + score handlers + tests | Medium | Railway |
| 3 | daemon_state_push on daemon WS connect | Small | Railway |
| 4 | Add current_activity to ParticipantState | Small | Daemon |
| 5 | Daemon word cloud state cache | Small | Daemon |
| 6 | Daemon word cloud router + tests | Medium | Daemon |
| 7 | Mount routers + wire state sync | Medium | Daemon |
| 8 | Switch participant JS to REST + broadcast handler | Small | Frontend |
| 9 | Switch host JS word submission to REST | Small | Frontend |
