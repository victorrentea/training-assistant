# Phase 4b: Q&A + Emoji Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate Q&A (stateful, personalized) and emoji reactions (stateless) end-to-end from Railway to daemon, using the Phase 4a broadcast infrastructure.

**Architecture:** Emoji: participant REST → daemon → POST to localhost:56789 overlay (fire-and-forget) + push to host local WS. Q&A: participant REST → daemon state + write-back broadcast + score_award + push to host local WS. Host Q&A: daemon localhost REST → state + broadcast via _ws_client + push to host local WS. A new `daemon/host_ws.py` module stores the single host browser WS connection for direct push.

**Tech Stack:** Python 3.12, FastAPI, httpx, websockets, asyncio, pytest

**Spec:** `docs/superpowers/specs/2026-04-03-qa-emoji-migration-design.md`

---

## Context

Phase 4a built the generic broadcast infrastructure (`_handle_broadcast` in Railway) and migrated word cloud as the first proof. This plan migrates two more features following the same patterns:

- **Write-back events** for participant-proxied calls: daemon sets `request.state.write_back_events`, middleware serializes to `X-Write-Back-Events` header, `proxy_handler.py` reads and sends over WS before `proxy_response`.
- **Host-direct calls** on daemon localhost: router calls `_ws_client.send()` for Railway broadcast + `send_to_host()` for host browser.
- **`set_ws_client()` injection**: module-level `_ws_client = None` + `set_ws_client(client)` function, wired in `__main__.py`.

### What changes

- New `daemon/host_ws.py` — stores single host browser WS reference for direct push
- `daemon/host_proxy.py` — modified to set/clear host WS on connect/disconnect
- New `daemon/emoji/` package — stateless emoji endpoint
- New `daemon/qa/` package — Q&A state + participant/host endpoints
- `daemon/host_server.py` — mount emoji + Q&A routers
- `daemon/__main__.py` — wire ws_client + extend daemon_state_push handler for Q&A
- `features/ws/router.py` — extend daemon_state_push with qa_questions
- `static/participant.js` — REST for emoji/qa + qa_updated handler
- `static/host.js` — REST for host qa_submit + qa_updated handler

### What stays the same

- Old WS handlers for `emoji_reaction`, `qa_submit`, `qa_upvote` stay on Railway for backward compat
- Railway Q&A REST endpoints (`features/qa/router.py`) stay as dead code
- No `qa_state_sync` — Railway's qa_questions goes stale; old cached JS must refresh

---

## Design Decisions

### Host WS push

The host browser connects to daemon's localhost:8081 directly (NOT through Railway). When daemon needs to push messages to the host (emoji reactions, Q&A updates), it sends directly over the host's local WS connection stored in `daemon/host_ws.py`. Single connection only — same pattern as Railway's `state.daemon_ws`.

### Daemon-side name resolution

`build_question_list()` resolves author UUIDs to display names using `participant_state.participant_names` and `participant_state.participant_avatars`. The broadcast includes both resolved names (for rendering) and raw UUIDs (for client-side `is_own`/`has_upvoted` checks). Participant JS does NOT need name/avatar maps.

### No Q&A activity gate

Railway's `qa_submit` WS handler accepts submissions regardless of `current_activity`. This migration preserves that behavior — no activity gate on the daemon Q&A submit endpoint.

### Overlay POST is fire-and-forget

The daemon POSTs emoji reactions to `localhost:56789` (victor-macos-addons desktop overlay). If that service isn't running, the exception is silently caught. The FastAPI server on victor-macos-addons will be configured separately in a future task.

---

## File Structure

### Create
- `daemon/host_ws.py` — host WS push module (set/clear/send_to_host)
- `daemon/emoji/__init__.py` — package init
- `daemon/emoji/router.py` — emoji reaction endpoint
- `daemon/qa/__init__.py` — package init
- `daemon/qa/state.py` — QAState singleton
- `daemon/qa/router.py` — participant + host Q&A endpoints
- `tests/daemon/test_host_ws.py` — host WS module tests
- `tests/daemon/test_emoji_router.py` — emoji router tests
- `tests/daemon/test_qa_state.py` — Q&A state tests
- `tests/daemon/test_qa_router.py` — Q&A router tests

### Modify
- `daemon/host_proxy.py` — store host WS on connect/disconnect
- `daemon/host_server.py` — mount emoji + Q&A routers
- `daemon/__main__.py` — wire ws_client + qa_state sync
- `features/ws/router.py` — extend daemon_state_push with qa_questions
- `static/participant.js` — REST for emoji/qa + qa_updated handler
- `static/host.js` — REST for host qa_submit + qa_updated handler

---

## Tasks

### Task 1: Create host WS push module + tests

**Files:**
- Create: `daemon/host_ws.py`
- Create: `tests/daemon/test_host_ws.py`

- [ ] **Step 1: Create `daemon/host_ws.py`**

```python
"""Host browser WebSocket push — single connection stored at module level.

The host browser connects to daemon's localhost:8081 via WebSocket.
This module stores that connection so daemon code can push messages
directly to the host without going through Railway.
"""
import json
import logging

logger = logging.getLogger(__name__)

_host_ws = None


def set_host_ws(ws):
    """Store the host browser's WS connection. Called when host connects."""
    global _host_ws
    _host_ws = ws


def clear_host_ws():
    """Clear the host WS reference. Called when host disconnects."""
    global _host_ws
    _host_ws = None


async def send_to_host(msg: dict):
    """Push a JSON message to the host browser. No-op if not connected."""
    if _host_ws is None:
        return
    try:
        await _host_ws.send_text(json.dumps(msg))
    except Exception:
        logger.debug("Failed to send to host WS")
```

- [ ] **Step 2: Create `tests/daemon/test_host_ws.py`**

```python
"""Tests for daemon host WS push module."""
import pytest
from unittest.mock import AsyncMock, patch

import daemon.host_ws as host_ws_mod
from daemon.host_ws import set_host_ws, clear_host_ws, send_to_host


class TestHostWs:
    def setup_method(self):
        host_ws_mod._host_ws = None

    def test_set_and_clear(self):
        mock_ws = AsyncMock()
        set_host_ws(mock_ws)
        assert host_ws_mod._host_ws is mock_ws
        clear_host_ws()
        assert host_ws_mod._host_ws is None

    @pytest.mark.anyio
    async def test_send_to_host_delivers_message(self):
        mock_ws = AsyncMock()
        set_host_ws(mock_ws)
        await send_to_host({"type": "test", "data": 123})
        mock_ws.send_text.assert_called_once()
        import json
        sent = json.loads(mock_ws.send_text.call_args[0][0])
        assert sent["type"] == "test"
        assert sent["data"] == 123

    @pytest.mark.anyio
    async def test_send_to_host_noop_when_disconnected(self):
        # Should not raise
        await send_to_host({"type": "test"})

    @pytest.mark.anyio
    async def test_send_to_host_handles_exception(self):
        mock_ws = AsyncMock()
        mock_ws.send_text.side_effect = Exception("connection closed")
        set_host_ws(mock_ws)
        # Should not raise
        await send_to_host({"type": "test"})
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/daemon/test_host_ws.py -v`
Expected: All pass

- [ ] **Step 4: Commit and push**

```bash
git add daemon/host_ws.py tests/daemon/test_host_ws.py
git commit -m "feat(daemon): add host WS push module for direct host browser messaging"
git pull --rebase origin master && git push origin master
```

---

### Task 2: Wire host WS into proxy_websocket

**Files:**
- Modify: `daemon/host_proxy.py`

- [ ] **Step 1: Read `daemon/host_proxy.py`**

Read the `proxy_websocket` function (lines 60-108). Note:
- Line 65: `await client_ws.accept()`
- Line 75: `try:` block starts
- Line 103: `finally:` block

- [ ] **Step 2: Add host WS detection and storage**

After line 65 (`await client_ws.accept()`), add:

```python
    is_host = path.endswith("__host__")
    if is_host:
        from daemon.host_ws import set_host_ws
        set_host_ws(client_ws)
```

In the `finally:` block (around line 103), BEFORE `await client_ws.close()`, add:

```python
        if is_host:
            from daemon.host_ws import clear_host_ws
            clear_host_ws()
```

Make sure `is_host` is defined before the `try:` block so it's accessible in `finally:`.

- [ ] **Step 3: Run tests**

Run: `pytest tests/daemon/ -q --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript`
Expected: All pass

- [ ] **Step 4: Commit and push**

```bash
git add daemon/host_proxy.py
git commit -m "feat(daemon): store host WS connection on connect for direct push"
git pull --rebase origin master && git push origin master
```

---

### Task 3: Create emoji router + tests

**Files:**
- Create: `daemon/emoji/__init__.py`
- Create: `daemon/emoji/router.py`
- Create: `tests/daemon/test_emoji_router.py`

- [ ] **Step 1: Create `daemon/emoji/__init__.py`**

Empty file.

- [ ] **Step 2: Create `daemon/emoji/router.py`**

```python
"""Daemon emoji reaction router — participant endpoint."""
import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from daemon.host_ws import send_to_host

logger = logging.getLogger(__name__)

participant_router = APIRouter(prefix="/api/participant/emoji", tags=["emoji"])


@participant_router.post("/reaction")
async def emoji_reaction(request: Request):
    """Participant sends an emoji reaction."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    emoji = str(body.get("emoji", "")).strip()
    if not emoji or len(emoji) > 4:
        return JSONResponse({"error": "Invalid emoji"}, status_code=400)

    # Forward to host browser (local WS)
    await send_to_host({"type": "emoji_reaction", "emoji": emoji})

    # Forward to desktop overlay (victor-macos-addons) — fire and forget
    try:
        async with httpx.AsyncClient() as client:
            await client.post("http://localhost:56789/emoji",
                              json={"emoji": emoji}, timeout=1.0)
    except Exception:
        pass  # overlay may not be running

    return JSONResponse({"ok": True})
```

- [ ] **Step 3: Create `tests/daemon/test_emoji_router.py`**

```python
"""Tests for daemon emoji router."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from starlette.testclient import TestClient
from fastapi import FastAPI

from daemon.emoji.router import participant_router


@pytest.fixture
def emoji_client():
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_externals():
    """Mock send_to_host and httpx for all emoji tests."""
    with patch("daemon.emoji.router.send_to_host", new_callable=AsyncMock) as mock_host, \
         patch("daemon.emoji.router.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
        yield {"host": mock_host, "httpx_client": mock_client}


class TestEmojiReaction:
    def test_valid_emoji(self, emoji_client):
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "🎉"},
                                  headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200

    def test_missing_participant_id(self, emoji_client):
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "🎉"})
        assert resp.status_code == 400

    def test_empty_emoji_rejected(self, emoji_client):
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": ""},
                                  headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400

    def test_long_emoji_rejected(self, emoji_client):
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "12345"},
                                  headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400

    def test_overlay_failure_does_not_break(self, emoji_client, mock_externals):
        """Overlay at localhost:56789 not running — should not fail."""
        mock_externals["httpx_client"].post.side_effect = Exception("Connection refused")
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "❤️"},
                                  headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200

    def test_sends_to_host_ws(self, emoji_client, mock_externals):
        emoji_client.post("/api/participant/emoji/reaction",
                           json={"emoji": "🎉"},
                           headers={"X-Participant-ID": "uuid1"})
        mock_externals["host"].assert_called_once()
        call_msg = mock_externals["host"].call_args[0][0]
        assert call_msg["type"] == "emoji_reaction"
        assert call_msg["emoji"] == "🎉"
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/daemon/test_emoji_router.py -v`
Expected: All pass

- [ ] **Step 5: Commit and push**

```bash
git add daemon/emoji/__init__.py daemon/emoji/router.py tests/daemon/test_emoji_router.py
git commit -m "feat(daemon): add emoji reaction endpoint with host WS + overlay forwarding"
git pull --rebase origin master && git push origin master
```

---

### Task 4: Create Q&A state + tests

**Files:**
- Create: `daemon/qa/__init__.py`
- Create: `daemon/qa/state.py`
- Create: `tests/daemon/test_qa_state.py`

- [ ] **Step 1: Create `daemon/qa/__init__.py`**

Empty file.

- [ ] **Step 2: Create `daemon/qa/state.py`**

```python
"""Q&A state cache for daemon.

Owns the Q&A questions state. Initial data comes from daemon_state_push.
"""
import threading
import time
import uuid as uuid_mod


class QAState:
    """Q&A state. Mutation methods run on uvicorn's single-threaded
    event loop (no lock needed). sync_from_restore runs on the main thread
    and uses _lock for cross-thread safety.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.questions: dict[str, dict] = {}

    def sync_from_restore(self, data: dict):
        """Update from daemon_state_push. Called from main thread."""
        with self._lock:
            if "qa_questions" in data:
                self.questions.clear()
                for qid, q in data["qa_questions"].items():
                    self.questions[qid] = {
                        **q,
                        "upvoters": set(q.get("upvoters", [])),
                    }

    def submit(self, author: str, text: str) -> str:
        """Submit a question. Returns the question ID."""
        qid = str(uuid_mod.uuid4())
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
        """Upvote a question. Returns (success, author_pid)."""
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

        Resolves author UUIDs to display names daemon-side. Includes
        author_uuid for client-side is_own check and upvoters as UUID
        list for client-side has_upvoted check.
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


# Module-level singleton
qa_state = QAState()
```

- [ ] **Step 3: Create `tests/daemon/test_qa_state.py`**

```python
"""Tests for daemon Q&A state."""
import pytest
from daemon.qa.state import QAState


class TestQAState:
    def setup_method(self):
        self.state = QAState()
        self.names = {"uuid1": "Alice", "uuid2": "Bob", "__host__": "Host"}
        self.avatars = {"uuid1": "avatar1.png", "uuid2": "avatar2.png"}

    def test_submit_creates_question(self):
        qid = self.state.submit("uuid1", "What is Python?")
        assert qid in self.state.questions
        q = self.state.questions[qid]
        assert q["text"] == "What is Python?"
        assert q["author"] == "uuid1"
        assert q["upvoters"] == set()
        assert q["answered"] is False

    def test_upvote_success(self):
        qid = self.state.submit("uuid1", "Question")
        success, author = self.state.upvote(qid, "uuid2")
        assert success is True
        assert author == "uuid1"
        assert "uuid2" in self.state.questions[qid]["upvoters"]

    def test_upvote_self_rejected(self):
        qid = self.state.submit("uuid1", "Question")
        success, _ = self.state.upvote(qid, "uuid1")
        assert success is False

    def test_upvote_duplicate_rejected(self):
        qid = self.state.submit("uuid1", "Question")
        self.state.upvote(qid, "uuid2")
        success, _ = self.state.upvote(qid, "uuid2")
        assert success is False

    def test_upvote_nonexistent_rejected(self):
        success, _ = self.state.upvote("bad-id", "uuid1")
        assert success is False

    def test_edit_text(self):
        qid = self.state.submit("uuid1", "Original")
        assert self.state.edit_text(qid, "Edited") is True
        assert self.state.questions[qid]["text"] == "Edited"

    def test_edit_nonexistent(self):
        assert self.state.edit_text("bad-id", "text") is False

    def test_delete(self):
        qid = self.state.submit("uuid1", "Question")
        assert self.state.delete(qid) is True
        assert qid not in self.state.questions

    def test_delete_nonexistent(self):
        assert self.state.delete("bad-id") is False

    def test_toggle_answered(self):
        qid = self.state.submit("uuid1", "Question")
        assert self.state.toggle_answered(qid, True) is True
        assert self.state.questions[qid]["answered"] is True
        assert self.state.toggle_answered(qid, False) is True
        assert self.state.questions[qid]["answered"] is False

    def test_clear(self):
        self.state.submit("uuid1", "Q1")
        self.state.submit("uuid2", "Q2")
        self.state.clear()
        assert self.state.questions == {}

    def test_build_question_list_resolves_names(self):
        self.state.submit("uuid1", "Question")
        result = self.state.build_question_list(self.names, self.avatars)
        assert len(result) == 1
        assert result[0]["author"] == "Alice"
        assert result[0]["author_uuid"] == "uuid1"
        assert result[0]["author_avatar"] == "avatar1.png"

    def test_build_question_list_sorted_by_upvotes(self):
        q1 = self.state.submit("uuid1", "Less popular")
        q2 = self.state.submit("uuid2", "More popular")
        self.state.upvote(q2, "uuid1")
        result = self.state.build_question_list(self.names, self.avatars)
        assert result[0]["text"] == "More popular"
        assert result[1]["text"] == "Less popular"

    def test_build_question_list_upvoters_as_list(self):
        qid = self.state.submit("uuid1", "Question")
        self.state.upvote(qid, "uuid2")
        result = self.state.build_question_list(self.names, self.avatars)
        assert isinstance(result[0]["upvoters"], list)
        assert result[0]["upvote_count"] == 1

    def test_sync_from_restore(self):
        data = {
            "qa_questions": {
                "q1": {
                    "id": "q1", "text": "Q1", "author": "uuid1",
                    "upvoters": ["uuid2"], "answered": True,
                    "timestamp": 1234.0,
                },
            },
        }
        self.state.sync_from_restore(data)
        assert "q1" in self.state.questions
        assert self.state.questions["q1"]["upvoters"] == {"uuid2"}
        assert self.state.questions["q1"]["answered"] is True
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/daemon/test_qa_state.py -v`
Expected: All pass

- [ ] **Step 5: Commit and push**

```bash
git add daemon/qa/__init__.py daemon/qa/state.py tests/daemon/test_qa_state.py
git commit -m "feat(daemon): add Q&A state cache with daemon-side name resolution"
git pull --rebase origin master && git push origin master
```

---

### Task 5: Create Q&A router + tests

**Files:**
- Create: `daemon/qa/router.py`
- Create: `tests/daemon/test_qa_router.py`

- [ ] **Step 1: Create `daemon/qa/router.py`**

```python
"""Daemon Q&A router — participant + host endpoints."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from daemon.host_ws import send_to_host
from daemon.participant.state import participant_state
from daemon.qa.state import qa_state

logger = logging.getLogger(__name__)

_ws_client = None


def set_ws_client(client):
    global _ws_client
    _ws_client = client


def _build_questions():
    """Helper: build question list with resolved names."""
    return qa_state.build_question_list(
        participant_state.participant_names,
        participant_state.participant_avatars,
    )


# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant/qa", tags=["qa"])


@participant_router.post("/submit")
async def submit_question(request: Request):
    """Participant submits a Q&A question."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    body = await request.json()
    text = str(body.get("text", "")).strip()
    if not text or len(text) > 280:
        return JSONResponse({"error": "Invalid text"}, status_code=400)

    # No activity gate — Railway accepts Q&A submissions regardless of current activity

    qa_state.submit(pid, text)
    questions = _build_questions()

    request.state.write_back_events = [
        {"type": "broadcast", "event": {"type": "qa_updated", "questions": questions}},
        {"type": "score_award", "participant_id": pid, "points": 100},
    ]

    await send_to_host({"type": "qa_updated", "questions": questions})

    return JSONResponse({"ok": True})


@participant_router.post("/upvote")
async def upvote_question(request: Request):
    """Participant upvotes a Q&A question."""
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

    await send_to_host({"type": "qa_updated", "questions": questions})

    return JSONResponse({"ok": True})


# ── Host router (called directly on daemon localhost) ──
# Host JS calls API('/qa/submit') which expands to /api/{session_id}/qa/submit.

host_router = APIRouter(prefix="/api/{session_id}/qa", tags=["qa"])


@host_router.post("/submit")
async def host_submit_question(request: Request):
    """Host submits a Q&A question — no scoring."""
    body = await request.json()
    text = str(body.get("text", "")).strip()
    if not text or len(text) > 280:
        return JSONResponse({"error": "Invalid text"}, status_code=400)

    qa_state.submit("__host__", text)
    await _send_qa_events()
    return JSONResponse({"ok": True})


@host_router.put("/question/{question_id}/text")
async def edit_question_text(question_id: str, request: Request):
    """Host edits a question's text."""
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
    """Host deletes a question."""
    if not qa_state.delete(question_id):
        return JSONResponse({"error": "Not found"}, status_code=404)
    await _send_qa_events()
    return JSONResponse({"ok": True})


@host_router.put("/question/{question_id}/answered")
async def toggle_answered(question_id: str, request: Request):
    """Host toggles a question's answered flag."""
    body = await request.json()
    answered = bool(body.get("answered", False))
    if not qa_state.toggle_answered(question_id, answered):
        return JSONResponse({"error": "Not found"}, status_code=404)
    await _send_qa_events()
    return JSONResponse({"ok": True})


@host_router.post("/clear")
async def clear_qa():
    """Host clears all Q&A questions."""
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
    await send_to_host({"type": "qa_updated", "questions": questions})
```

- [ ] **Step 2: Create `tests/daemon/test_qa_router.py`**

```python
"""Tests for daemon Q&A router."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from starlette.testclient import TestClient
from fastapi import FastAPI

from daemon.qa.router import participant_router, host_router
from daemon.qa.state import QAState
from daemon.participant.state import ParticipantState


@pytest.fixture
def fresh_qa_state():
    qas = QAState()
    with patch("daemon.qa.router.qa_state", qas):
        yield qas


@pytest.fixture
def fresh_participant_state():
    ps = ParticipantState()
    ps.participant_names = {"uuid1": "Alice", "uuid2": "Bob", "__host__": "Host"}
    ps.participant_avatars = {"uuid1": "a1.png", "uuid2": "a2.png"}
    with patch("daemon.qa.router.participant_state", ps):
        yield ps


@pytest.fixture
def mock_ws_client():
    mock = MagicMock()
    mock.send.return_value = True
    with patch("daemon.qa.router._ws_client", mock):
        yield mock


@pytest.fixture
def mock_host_ws():
    """Mock send_to_host — imported at module level in daemon.qa.router."""
    with patch("daemon.qa.router.send_to_host", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def participant_client(fresh_qa_state, fresh_participant_state, mock_host_ws):
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture
def host_client(fresh_qa_state, fresh_participant_state, mock_ws_client, mock_host_ws):
    app = FastAPI()
    app.include_router(host_router)
    return TestClient(app)


class TestParticipantSubmit:
    def test_submit_creates_question(self, participant_client, fresh_qa_state):
        resp = participant_client.post("/api/participant/qa/submit",
                                       json={"text": "What is Python?"},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        assert len(fresh_qa_state.questions) == 1

    def test_submit_empty_text_rejected(self, participant_client):
        resp = participant_client.post("/api/participant/qa/submit",
                                       json={"text": ""},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400

    def test_submit_long_text_rejected(self, participant_client):
        resp = participant_client.post("/api/participant/qa/submit",
                                       json={"text": "x" * 281},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400

    def test_submit_missing_pid(self, participant_client):
        resp = participant_client.post("/api/participant/qa/submit",
                                       json={"text": "Question?"})
        assert resp.status_code == 400

    def test_submit_sends_to_host(self, participant_client, mock_host_ws):
        participant_client.post("/api/participant/qa/submit",
                                json={"text": "Question?"},
                                headers={"X-Participant-ID": "uuid1"})
        mock_host_ws.assert_called_once()
        msg = mock_host_ws.call_args[0][0]
        assert msg["type"] == "qa_updated"


class TestParticipantUpvote:
    def test_upvote_success(self, participant_client, fresh_qa_state):
        qid = fresh_qa_state.submit("uuid1", "Question?")
        resp = participant_client.post("/api/participant/qa/upvote",
                                       json={"question_id": qid},
                                       headers={"X-Participant-ID": "uuid2"})
        assert resp.status_code == 200

    def test_upvote_self_rejected(self, participant_client, fresh_qa_state):
        qid = fresh_qa_state.submit("uuid1", "Question?")
        resp = participant_client.post("/api/participant/qa/upvote",
                                       json={"question_id": qid},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 409

    def test_upvote_duplicate_rejected(self, participant_client, fresh_qa_state):
        qid = fresh_qa_state.submit("uuid1", "Question?")
        fresh_qa_state.upvote(qid, "uuid2")
        resp = participant_client.post("/api/participant/qa/upvote",
                                       json={"question_id": qid},
                                       headers={"X-Participant-ID": "uuid2"})
        assert resp.status_code == 409

    def test_upvote_missing_question_id(self, participant_client):
        resp = participant_client.post("/api/participant/qa/upvote",
                                       json={},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400


class TestHostEndpoints:
    def test_host_submit(self, host_client, fresh_qa_state, mock_ws_client):
        resp = host_client.post("/api/test-session/qa/submit",
                                json={"text": "Host question"})
        assert resp.status_code == 200
        assert len(fresh_qa_state.questions) == 1
        q = list(fresh_qa_state.questions.values())[0]
        assert q["author"] == "__host__"

    def test_edit_question(self, host_client, fresh_qa_state, mock_ws_client):
        qid = fresh_qa_state.submit("uuid1", "Original")
        resp = host_client.put(f"/api/test-session/qa/question/{qid}/text",
                               json={"text": "Edited"})
        assert resp.status_code == 200
        assert fresh_qa_state.questions[qid]["text"] == "Edited"

    def test_delete_question(self, host_client, fresh_qa_state, mock_ws_client):
        qid = fresh_qa_state.submit("uuid1", "To delete")
        resp = host_client.delete(f"/api/test-session/qa/question/{qid}")
        assert resp.status_code == 200
        assert qid not in fresh_qa_state.questions

    def test_toggle_answered(self, host_client, fresh_qa_state, mock_ws_client):
        qid = fresh_qa_state.submit("uuid1", "Question")
        resp = host_client.put(f"/api/test-session/qa/question/{qid}/answered",
                               json={"answered": True})
        assert resp.status_code == 200
        assert fresh_qa_state.questions[qid]["answered"] is True

    def test_clear(self, host_client, fresh_qa_state, mock_ws_client):
        fresh_qa_state.submit("uuid1", "Q1")
        fresh_qa_state.submit("uuid2", "Q2")
        resp = host_client.post("/api/test-session/qa/clear", json={})
        assert resp.status_code == 200
        assert fresh_qa_state.questions == {}

    def test_edit_nonexistent_404(self, host_client):
        resp = host_client.put("/api/test-session/qa/question/bad-id/text",
                               json={"text": "New"})
        assert resp.status_code == 404

    def test_host_submit_sends_broadcast(self, host_client, mock_ws_client):
        host_client.post("/api/test-session/qa/submit",
                         json={"text": "Question"})
        assert mock_ws_client.send.call_count >= 1
        broadcast = mock_ws_client.send.call_args_list[0][0][0]
        assert broadcast["type"] == "broadcast"
        assert broadcast["event"]["type"] == "qa_updated"
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/daemon/test_qa_router.py -v`
Expected: All pass

- [ ] **Step 4: Commit and push**

```bash
git add daemon/qa/router.py tests/daemon/test_qa_router.py
git commit -m "feat(daemon): add Q&A router with participant + host endpoints"
git pull --rebase origin master && git push origin master
```

---

### Task 6: Mount emoji + Q&A routers on daemon + wire state sync

**Files:**
- Modify: `daemon/host_server.py`
- Modify: `daemon/__main__.py`

- [ ] **Step 1: Read current files**

Read:
- `daemon/host_server.py` — find where `wc_participant_router` and `wc_host_router` are mounted (lines 71-74) and where the catch-all is (line 82-84)
- `daemon/__main__.py` — find where `set_wc_ws(ws_client)` is called (around line 342) and where `_handle_daemon_state_push` is defined (around line 348)

- [ ] **Step 2: Mount routers in host_server.py**

After lines 73-74 (where wordcloud routers are mounted), add:

```python
    from daemon.emoji.router import participant_router as emoji_participant_router
    from daemon.qa.router import participant_router as qa_participant_router
    from daemon.qa.router import host_router as qa_host_router
    app.include_router(emoji_participant_router)  # /api/participant/emoji/*
    app.include_router(qa_participant_router)      # /api/participant/qa/*
    app.include_router(qa_host_router)             # /api/{session_id}/qa/*
```

All must be BEFORE the catch-all `@app.api_route("/api/{path:path}", ...)`.

- [ ] **Step 3: Wire ws_client and state sync in __main__.py**

Find where `set_wc_ws(ws_client)` is called. After it, add:

```python
    from daemon.qa.router import set_ws_client as set_qa_ws
    set_qa_ws(ws_client)
```

Note: The emoji router does NOT need `ws_client` — it only uses `send_to_host()` and HTTP POST to the overlay. No Railway broadcast needed for emoji.

Find the existing `_handle_daemon_state_push` function. Add `qa_state.sync_from_restore(data)` to it:

```python
    from daemon.qa.state import qa_state

    def _handle_daemon_state_push(data):
        participant_state.sync_from_restore(data)
        wordcloud_state.sync_from_restore(data)
        qa_state.sync_from_restore(data)
```

**Important:** Replace the existing `_handle_daemon_state_push` function — don't create a second one.

- [ ] **Step 4: Run tests**

Run: `pytest tests/daemon/ -q --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript`
Expected: All pass

Run: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load -x`
Expected: All pass

- [ ] **Step 5: Commit and push**

```bash
git add daemon/host_server.py daemon/__main__.py
git commit -m "feat(daemon): mount emoji + Q&A routers, wire state sync for Q&A"
git pull --rebase origin master && git push origin master
```

---

### Task 7: Extend daemon_state_push with Q&A questions

**Files:**
- Modify: `features/ws/router.py`

- [ ] **Step 1: Read the daemon_state_push block**

Read `features/ws/router.py` around lines 708-722 to see the current `send_json` dict.

- [ ] **Step 2: Add qa_questions to the push**

In the `send_json` dict (inside `daemon_websocket_endpoint()`), after the `"wordcloud_topic"` line, add:

```python
            "qa_questions": {
                qid: {**q, "upvoters": list(q["upvoters"])}
                for qid, q in state.qa_questions.items()
            },
```

Note: `q["upvoters"]` is a `set` in AppState — must convert to `list` for JSON serialization.

- [ ] **Step 3: Run tests**

Run: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load -x`
Expected: All pass

- [ ] **Step 4: Commit and push**

```bash
git add features/ws/router.py
git commit -m "feat: extend daemon_state_push with qa_questions for Q&A migration"
git pull --rebase origin master && git push origin master
```

---

### Task 8: Switch participant JS — emoji + Q&A to REST + qa_updated handler

**Files:**
- Modify: `static/participant.js`

- [ ] **Step 1: Read the relevant sections**

Read `static/participant.js` and find:
- `sendWS('emoji_reaction'` (around line 3349)
- `sendWS('qa_submit'` (around line 3413)
- `sendWS('qa_upvote'` (around line 3422)
- The `handleMessage` switch statement where `wordcloud_updated` was added (around line 2880)
- `myUUID` variable (line 159)

- [ ] **Step 2: Replace emoji WS with REST**

Find:
```javascript
sendWS('emoji_reaction', { emoji });
```

Replace with:
```javascript
participantApi('emoji/reaction', { emoji });
```

Also remove the `if (!ws) return;` guard just above it (line 3348) since emoji no longer needs WS. Replace it with just a return-if-no-emoji check or remove the WS guard entirely. Read the surrounding function carefully to decide.

- [ ] **Step 3: Replace Q&A submit WS with REST**

Find:
```javascript
sendWS('qa_submit', { text });
```

Replace with:
```javascript
participantApi('qa/submit', { text });
```

Also remove or adjust the `!ws` guard in the containing `if` statement (the `if (!text || !ws) return;` line). Since this is now REST, the WS check is stale — change to `if (!text) return;`.

- [ ] **Step 4: Replace Q&A upvote WS with REST**

Find:
```javascript
sendWS('qa_upvote', { question_id: questionId });
```

Replace with:
```javascript
participantApi('qa/upvote', { question_id: questionId });
```

Also remove the `if (!ws) return;` guard above it.

- [ ] **Step 5: Add qa_updated handler**

In the `handleMessage` switch statement, near the `wordcloud_updated` case (around line 2880), add:

```javascript
      case 'qa_updated': {
        const myQuestions = (msg.questions || []).map(q => ({
            ...q,
            is_own: q.author_uuid === myUUID,
            has_upvoted: (q.upvoters || []).includes(myUUID),
        }));
        renderQAScreen(myQuestions);
        break;
      }
```

Note: `myUUID` is a module-level variable (line 159). The broadcast includes `author` (display name), `author_uuid`, `author_avatar`, `upvote_count`, `upvoters` (UUID list). After mapping, the data matches what `renderQAScreen` / `updateQAList` expects.

- [ ] **Step 6: Run tests**

Run: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load -x`
Expected: All pass

- [ ] **Step 7: Commit and push**

```bash
git add static/participant.js
git commit -m "feat: switch participant emoji + Q&A from WS to REST + add qa_updated broadcast handler"
git pull --rebase origin master && git push origin master
```

---

### Task 9: Switch host JS — Q&A submit to REST + qa_updated handler

**Files:**
- Modify: `static/host.js`

- [ ] **Step 1: Read the relevant sections**

Read `static/host.js` and find:
- `sendWS('qa_submit'` (around line 2259)
- The message handling chain where `emoji_reaction` is handled (around line 377)

- [ ] **Step 2: Replace host Q&A submit WS with REST**

Find:
```javascript
sendWS('qa_submit', { text });
```

Replace with:
```javascript
fetch(API('/qa/submit'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text })
});
```

Also adjust the `!ws` guard above it — change `if (!text || !ws) return;` to `if (!text) return;`.

- [ ] **Step 3: Add qa_updated handler**

In the message handling chain, after the `emoji_reaction` handler (around line 378), add:

```javascript
} else if (msg.type === 'qa_updated') {
    renderQAList(msg.questions || []);
```

Note: The daemon already resolves author names/avatars and computes `upvote_count`. The host `renderQAList` function expects `author`, `author_avatar`, `upvote_count`, `answered`, `id`, `text` — all present in the broadcast. No additional mapping needed.

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load -x`
Expected: All pass

- [ ] **Step 5: Commit and push**

```bash
git add static/host.js
git commit -m "feat: switch host Q&A submit from WS to REST + add qa_updated handler"
git pull --rebase origin master && git push origin master
```

---

## Verification

After all tasks complete:

1. **Daemon tests**: `pytest tests/daemon/ -q --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript` — all pass
2. **Full test suite**: `pytest tests/ -q -k "not nightly and not docker and not e2e" --ignore=tests/daemon/test_daemon.py --ignore=tests/daemon/transcript --ignore=tests/docker --ignore=tests/integration/test_llm_cleaner.py --ignore=tests/load` — all pass
3. **Manual test**:
   - Start Railway backend: `python3 -m uvicorn main:app --port 8000`
   - Start daemon: `python3 -m daemon`
   - Open participant and host pages
   - **Emoji**: click emoji on participant → should float on host panel
   - **Q&A submit**: participant submits question → appears on host and other participants
   - **Q&A upvote**: participant upvotes → count updates on all clients
   - **Host actions**: host edits/deletes/toggles answered → updates on all clients
   - Check browser network tab: participant sends REST calls (not WS)
   - Verify daemon continues working if localhost:56789 (overlay) is not listening

---

## Future work (not in this plan)

- **victor-macos-addons FastAPI**: configure a FastAPI server on `localhost:56789` to receive emoji POSTs from daemon. This is a separate project/repo.

---

## Summary

| Task | Description | Complexity | Changes |
|------|-------------|------------|---------|
| 1 | Host WS push module + tests | Small | Daemon |
| 2 | Wire host WS into proxy_websocket | Small | Daemon |
| 3 | Emoji router + tests | Medium | Daemon |
| 4 | Q&A state + tests | Medium | Daemon |
| 5 | Q&A router + tests | Large | Daemon |
| 6 | Mount routers + wire state sync | Medium | Daemon |
| 7 | Extend daemon_state_push with qa_questions | Small | Railway |
| 8 | Switch participant JS — emoji + Q&A to REST | Medium | Frontend |
| 9 | Switch host JS — Q&A submit + qa_updated handler | Small | Frontend |
