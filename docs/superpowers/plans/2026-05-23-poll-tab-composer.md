# Poll Tab Composer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a host-only Poll tab composer that live-syncs draft to the daemon via three endpoints (`PUT /poll/update`, `POST /poll/start`, `POST /poll/stop`). No participant rendering yet.

**Architecture:** Mirror the existing `daemon/quiz/` module structure (`__init__.py`, `state.py`, `router.py`) for the backend. On the host, fill in the empty `#tab-content-poll` left pane and add a new `#center-poll` panel parallel to `#center-quiz`. Vanilla JS module with module-local state, 300ms debounced PUT on text edits, immediate PUT on structural changes (Multi toggle, preset selection, row add).

**Tech Stack:** FastAPI + Pydantic (daemon), vanilla HTML/CSS/JS (host), pytest + FastAPI TestClient (tests).

**Spec:** [`docs/superpowers/specs/2026-05-23-poll-tab-composer-design.md`](../specs/2026-05-23-poll-tab-composer-design.md)

---

## File Structure

**New files:**
- `daemon/poll/__init__.py` — empty package marker
- `daemon/poll/state.py` — `PollData` Pydantic model + `PollState` dataclass + `poll_state` singleton
- `daemon/poll/router.py` — `host_router` with `PUT /update`, `POST /start`, `POST /stop`
- `tests/daemon/poll/__init__.py` — empty package marker
- `tests/daemon/poll/test_poll_router.py` — endpoint behavior tests

**Modified files:**
- `daemon/host_server.py` — register `poll_host_router`
- `docs/openapi.yaml` — regenerated snapshot (auto)
- `API.md` — regenerated reference (auto)
- `static/host.html` — fill `#tab-content-poll`, add `#center-poll`
- `static/host.css` — poll composer styles
- `static/host.js` — poll composer module + `updateCenterPanel` includes 'poll'

**Why this split:** The poll module follows the established `daemon/quiz/` layout one-for-one. State is in its own file so it can be patched in tests the same way `quiz_state` is. The router stays under 80 lines (three thin endpoints), so a single file is appropriate.

---

## Task 1: Create poll state module

**Files:**
- Create: `daemon/poll/__init__.py`
- Create: `daemon/poll/state.py`

- [ ] **Step 1: Create empty package marker**

Create `daemon/poll/__init__.py` with empty content (zero bytes).

- [ ] **Step 2: Write the state module**

Create `daemon/poll/state.py`:

```python
"""Poll feature state — host draft + started flag.

Mirrors the daemon/quiz/state.py pattern: module-level singleton, mutable in place.
No persistence — state lives only in memory and resets on daemon restart.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel


class PollData(BaseModel):
    """Latest draft pushed by the host composer."""
    question: str
    options: list[str]
    multi: bool


@dataclass
class PollState:
    data: Optional[PollData] = None
    started: bool = False

    def reset(self) -> None:
        self.data = None
        self.started = False


poll_state = PollState()
```

- [ ] **Step 3: Commit**

```bash
git add daemon/poll/__init__.py daemon/poll/state.py
git commit -m "feat(poll): add poll state module (PollData + PollState singleton)"
```

---

## Task 2: Write test scaffolding for poll router

**Files:**
- Create: `tests/daemon/poll/__init__.py`
- Create: `tests/daemon/poll/test_poll_router.py`

- [ ] **Step 1: Create empty package marker**

Create `tests/daemon/poll/__init__.py` with empty content.

- [ ] **Step 2: Write the test file with fixtures + a smoke import test**

Create `tests/daemon/poll/test_poll_router.py`:

```python
"""Tests for daemon poll router — host-only endpoints."""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def fresh_poll_state():
    from daemon.poll.state import PollState
    ps = PollState()
    with patch("daemon.poll.router.poll_state", ps):
        yield ps


@pytest.fixture
def host_client(fresh_poll_state):
    from daemon.poll.router import host_router
    app = FastAPI()
    app.include_router(host_router)
    return TestClient(app)


_SAMPLE_BODY = {
    "question": "How was lunch?",
    "options": ["Great", "Meh"],
    "multi": False,
}


def test_router_importable():
    from daemon.poll.router import host_router  # noqa: F401
```

- [ ] **Step 3: Run the test — expect ImportError**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/poll/test_poll_router.py -v --confcutdir=tests/daemon`

Expected: FAIL with `ModuleNotFoundError: No module named 'daemon.poll.router'`. (This drives Task 3.)

- [ ] **Step 4: Commit test scaffolding**

```bash
git add tests/daemon/poll/__init__.py tests/daemon/poll/test_poll_router.py
git commit -m "test(poll): add test scaffolding for poll router"
```

---

## Task 3: Implement `PUT /poll/update` endpoint

**Files:**
- Create: `daemon/poll/router.py`
- Modify: `tests/daemon/poll/test_poll_router.py`

- [ ] **Step 1: Add failing test for /update**

Append to `tests/daemon/poll/test_poll_router.py`:

```python
class TestPollUpdate:
    def test_update_stores_data(self, host_client, fresh_poll_state):
        resp = host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        assert resp.status_code == 204
        assert fresh_poll_state.data is not None
        assert fresh_poll_state.data.question == "How was lunch?"
        assert fresh_poll_state.data.options == ["Great", "Meh"]
        assert fresh_poll_state.data.multi is False

    def test_update_does_not_set_started(self, host_client, fresh_poll_state):
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        assert fresh_poll_state.started is False

    def test_update_accepts_incomplete_draft(self, host_client, fresh_poll_state):
        resp = host_client.put("/api/test-session/host/poll/update", json={
            "question": "",
            "options": ["Only one"],
            "multi": False,
        })
        assert resp.status_code == 204
        assert fresh_poll_state.data.question == ""
        assert fresh_poll_state.data.options == ["Only one"]
```

- [ ] **Step 2: Run the test — expect failure**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/poll/test_poll_router.py::TestPollUpdate -v --confcutdir=tests/daemon`

Expected: FAIL with `ModuleNotFoundError: No module named 'daemon.poll.router'`.

- [ ] **Step 3: Create the router with `/update`**

Create `daemon/poll/router.py`:

```python
"""Poll endpoints — host-only (called directly on daemon localhost).

No participant router yet; participant rendering is a follow-up.
"""
import logging

from fastapi import APIRouter, Response

from daemon.poll.state import PollData, poll_state

logger = logging.getLogger(__name__)


host_router = APIRouter(prefix="/api/{session_id}/host/poll", tags=["poll"])


@host_router.put("/update", status_code=204)
async def update_poll(body: PollData):
    """Host pushes the latest draft of the poll composer."""
    poll_state.data = body
    logger.debug("← poll/update: %r (%d options, multi=%s)", body.question, len(body.options), body.multi)
    return Response(status_code=204)
```

- [ ] **Step 4: Run the test — expect pass**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/poll/test_poll_router.py::TestPollUpdate -v --confcutdir=tests/daemon`

Expected: All 3 `TestPollUpdate` tests PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/poll/router.py tests/daemon/poll/test_poll_router.py
git commit -m "feat(poll): add PUT /poll/update endpoint with draft sync"
```

---

## Task 4: Implement `POST /poll/start` endpoint

**Files:**
- Modify: `daemon/poll/router.py`
- Modify: `tests/daemon/poll/test_poll_router.py`

- [ ] **Step 1: Add failing tests for /start**

Append to `tests/daemon/poll/test_poll_router.py`:

```python
class TestPollStart:
    def test_start_with_valid_draft_returns_204(self, host_client, fresh_poll_state):
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        resp = host_client.post("/api/test-session/host/poll/start")
        assert resp.status_code == 204
        assert fresh_poll_state.started is True

    def test_start_with_no_draft_returns_409(self, host_client, fresh_poll_state):
        resp = host_client.post("/api/test-session/host/poll/start")
        assert resp.status_code == 409
        assert fresh_poll_state.started is False

    def test_start_with_empty_question_returns_409(self, host_client, fresh_poll_state):
        host_client.put("/api/test-session/host/poll/update", json={
            "question": "   ",
            "options": ["A", "B"],
            "multi": False,
        })
        resp = host_client.post("/api/test-session/host/poll/start")
        assert resp.status_code == 409
        assert fresh_poll_state.started is False

    def test_start_with_fewer_than_two_options_returns_409(self, host_client, fresh_poll_state):
        host_client.put("/api/test-session/host/poll/update", json={
            "question": "Q?",
            "options": ["only"],
            "multi": False,
        })
        resp = host_client.post("/api/test-session/host/poll/start")
        assert resp.status_code == 409
        assert fresh_poll_state.started is False

    def test_start_ignores_empty_options_when_counting(self, host_client, fresh_poll_state):
        host_client.put("/api/test-session/host/poll/update", json={
            "question": "Q?",
            "options": ["A", "", "B"],
            "multi": False,
        })
        resp = host_client.post("/api/test-session/host/poll/start")
        # Client should never send empty options, but if a draft slipped through with one,
        # the trimmed count must still be >= 2. Here A and B both pass, so accept.
        assert resp.status_code == 204
        assert fresh_poll_state.started is True

    def test_start_is_idempotent(self, host_client, fresh_poll_state):
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        host_client.post("/api/test-session/host/poll/start")
        resp = host_client.post("/api/test-session/host/poll/start")
        assert resp.status_code == 204
        assert fresh_poll_state.started is True
```

- [ ] **Step 2: Run the tests — expect failure**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/poll/test_poll_router.py::TestPollStart -v --confcutdir=tests/daemon`

Expected: FAIL with 404 (endpoint not registered yet).

- [ ] **Step 3: Add `/start` to the router**

Edit `daemon/poll/router.py` and append after the `update_poll` function:

```python
@host_router.post("/start", status_code=204)
async def start_poll():
    """Host opens the current draft as a live poll."""
    data = poll_state.data
    if data is None:
        return JSONResponse({"error": "No draft to start"}, status_code=409)
    if not data.question.strip():
        return JSONResponse({"error": "Question is empty"}, status_code=409)
    nonempty = [o for o in data.options if o.strip()]
    if len(nonempty) < 2:
        return JSONResponse({"error": "Need at least 2 non-empty options"}, status_code=409)

    poll_state.started = True
    logger.info("◆ poll started: %r (%d options, multi=%s)", data.question, len(nonempty), data.multi)
    return Response(status_code=204)
```

Add `JSONResponse` to the `fastapi` import line at the top of the file:

```python
from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
```

- [ ] **Step 4: Run the tests — expect pass**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/poll/test_poll_router.py::TestPollStart -v --confcutdir=tests/daemon`

Expected: All 6 `TestPollStart` tests PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/poll/router.py tests/daemon/poll/test_poll_router.py
git commit -m "feat(poll): add POST /poll/start with draft validation"
```

---

## Task 5: Implement `POST /poll/stop` endpoint

**Files:**
- Modify: `daemon/poll/router.py`
- Modify: `tests/daemon/poll/test_poll_router.py`

- [ ] **Step 1: Add failing tests for /stop**

Append to `tests/daemon/poll/test_poll_router.py`:

```python
class TestPollStop:
    def test_stop_clears_data_and_started(self, host_client, fresh_poll_state):
        host_client.put("/api/test-session/host/poll/update", json=_SAMPLE_BODY)
        host_client.post("/api/test-session/host/poll/start")
        assert fresh_poll_state.data is not None
        assert fresh_poll_state.started is True

        resp = host_client.post("/api/test-session/host/poll/stop")
        assert resp.status_code == 204
        assert fresh_poll_state.data is None
        assert fresh_poll_state.started is False

    def test_stop_is_idempotent(self, host_client, fresh_poll_state):
        # No draft, no start — stop should still succeed.
        resp = host_client.post("/api/test-session/host/poll/stop")
        assert resp.status_code == 204
        assert fresh_poll_state.data is None
        assert fresh_poll_state.started is False
```

- [ ] **Step 2: Run the tests — expect failure**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/poll/test_poll_router.py::TestPollStop -v --confcutdir=tests/daemon`

Expected: FAIL with 404.

- [ ] **Step 3: Add `/stop` to the router**

Append to `daemon/poll/router.py`:

```python
@host_router.post("/stop", status_code=204)
async def stop_poll():
    """Host clears the poll draft and stops any running poll."""
    had_data = poll_state.data is not None
    poll_state.reset()
    if had_data:
        logger.info("◆ poll stopped")
    return Response(status_code=204)
```

- [ ] **Step 4: Run the tests — expect pass**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/poll/test_poll_router.py::TestPollStop -v --confcutdir=tests/daemon`

Expected: Both `TestPollStop` tests PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/poll/router.py tests/daemon/poll/test_poll_router.py
git commit -m "feat(poll): add POST /poll/stop with idempotent reset"
```

---

## Task 6: Register poll router in host_server.py

**Files:**
- Modify: `daemon/host_server.py:153-158` (alongside quiz routers)

- [ ] **Step 1: Register the router**

In `daemon/host_server.py`, find the block that registers `quiz_host_router` (around line 154–158) and add poll registration right after it.

Locate:

```python
    from daemon.leaderboard.router import router as leaderboard_router
    from daemon.quiz.router import host_router as quiz_host_router
    from daemon.quiz.router import participant_router as quiz_participant_router
    app.include_router(quiz_participant_router)   # /api/participant/quiz/*
    app.include_router(quiz_host_router)          # /api/{session_id}/quiz/*
    app.include_router(leaderboard_router)        # /api/{session_id}/leaderboard/*
```

Replace with:

```python
    from daemon.leaderboard.router import router as leaderboard_router
    from daemon.poll.router import host_router as poll_host_router
    from daemon.quiz.router import host_router as quiz_host_router
    from daemon.quiz.router import participant_router as quiz_participant_router
    app.include_router(quiz_participant_router)   # /api/participant/quiz/*
    app.include_router(quiz_host_router)          # /api/{session_id}/quiz/*
    app.include_router(poll_host_router)          # /api/{session_id}/host/poll/*
    app.include_router(leaderboard_router)        # /api/{session_id}/leaderboard/*
```

- [ ] **Step 2: Verify the app boots and routes are live**

Run: `uv run --extra dev --extra daemon python -c "from daemon.host_server import create_app; app = create_app('http://test'); paths = [r.path for r in app.routes]; print('\n'.join(p for p in paths if 'poll' in p))"`

Expected output (3 lines):
```
/api/{session_id}/host/poll/update
/api/{session_id}/host/poll/start
/api/{session_id}/host/poll/stop
```

- [ ] **Step 3: Commit**

```bash
git add daemon/host_server.py
git commit -m "feat(poll): register poll_host_router in daemon app"
```

---

## Task 7: Regenerate OpenAPI snapshot + API.md

**Files:**
- Modify: `docs/openapi.yaml`
- Modify: `API.md`

- [ ] **Step 1: Confirm the contract test currently fails (snapshot drift)**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/test_api_contract.py::TestOpenApiSnapshot -v --confcutdir=tests/daemon`

Expected: FAIL — `test_paths_match` reports the three new poll paths missing from the snapshot.

- [ ] **Step 2: Regenerate the OpenAPI snapshot**

Run: `uv run --extra dev --extra daemon python -m tests.daemon.test_api_contract --regenerate`

Expected output line:
```
Regenerated docs/openapi.yaml (N paths, M schemas)
```
(N goes up by 3 from before, M goes up by 1 for `PollData`.)

- [ ] **Step 3: Regenerate API.md**

Run: `uv run --extra dev --extra daemon python3 scripts/generate_apis_md.py --output API.md`

- [ ] **Step 4: Re-run contract tests — expect pass**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/test_api_contract.py -v --confcutdir=tests/daemon`

Expected: ALL contract tests PASS, including `test_all_operations_have_x_feature` (poll router has `tags=["poll"]` so `x-feature: poll` is added automatically by `enrich_openapi_contract`).

- [ ] **Step 5: Commit the regenerated docs**

```bash
git add docs/openapi.yaml API.md
git commit -m "docs(poll): regenerate openapi.yaml + API.md for poll endpoints"
```

---

## Task 8: Add HTML for Poll tab left pane

**Files:**
- Modify: `static/host.html:118-119`

- [ ] **Step 1: Replace the placeholder left pane**

In `static/host.html`, find:

```html
    <!-- Poll tab content (placeholder) -->
    <div id="tab-content-poll" class="tab-content" style="display:none;"></div>
```

Replace with:

```html
    <!-- Poll tab content -->
    <div id="tab-content-poll" class="tab-content" style="display:none;">
      <div class="poll-left">
        <textarea id="poll-question" class="poll-question" rows="2" placeholder="Question…"></textarea>
        <div class="poll-controls-row">
          <label class="poll-multi-label">
            <input type="checkbox" id="poll-multi" />
            Multi
          </label>
          <button class="btn btn-success" id="poll-start-btn" disabled>Start</button>
        </div>
        <div class="poll-quick-section">
          <div class="poll-quick-label">Quick Questions</div>
          <div class="poll-quick-row">
            <button class="btn btn-secondary poll-quick-btn" data-preset="yesno">Yes / No</button>
            <button class="btn btn-secondary poll-quick-btn" data-preset="truefalse">True / False</button>
            <button class="btn btn-secondary poll-quick-btn" data-preset="rating15">1–5 rating</button>
            <button class="btn btn-secondary poll-quick-btn" data-preset="energy">Energy Level</button>
          </div>
        </div>
      </div>
    </div>
```

- [ ] **Step 2: Visually verify in the browser (no JS yet — UI will be inert)**

Run the daemon: `python3 -m daemon` in one terminal.

Open `http://localhost:8081/` in a browser, sign in (Basic Auth — credentials in `~/.training-assistants-secrets.env`), click the Poll tab. You should see: question textarea, Start button (disabled), Multi checkbox, four Quick Questions buttons. No interactivity yet — styling will likely be ugly until Task 10.

- [ ] **Step 3: Commit**

```bash
git add static/host.html
git commit -m "feat(poll): scaffold Poll tab left pane HTML"
```

---

## Task 9: Add HTML for Poll center pane

**Files:**
- Modify: `static/host.html` (insert after `#center-quiz` block, around line 247)

- [ ] **Step 1: Find the right insertion point**

Locate the closing `</div>` of `#center-quiz` (around line 247 in `static/host.html`):

```html
    <!-- Quiz results panel -->
    <div id="center-quiz" class="center-panel" style="display:none;">
      ...
    </div>
```

- [ ] **Step 2: Insert the `#center-poll` panel directly after `#center-quiz`'s closing div**

Add:

```html
    <!-- Poll composer panel -->
    <div id="center-poll" class="center-panel" style="display:none;">
      <h2 class="poll-center-title">👍 Poll Options</h2>
      <div id="poll-options-container" class="poll-options-container"></div>
      <button id="poll-clear-btn" class="btn btn-danger poll-clear-btn">Clear All</button>
    </div>
```

- [ ] **Step 3: Commit**

```bash
git add static/host.html
git commit -m "feat(poll): add center-poll panel scaffold"
```

---

## Task 10: Add CSS for poll composer

**Files:**
- Modify: `static/host.css` (append to end of file)

- [ ] **Step 1: Append the styles**

Append to `static/host.css`:

```css
/* ── Poll tab — left pane ─────────────────────────────────────────── */
.poll-left {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-top: 0.75rem;
}

.poll-question {
  width: 100%;
  min-height: calc(2.4rem * 2);
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--surface2);
  color: var(--text);
  font-size: 0.95rem;
  font-family: inherit;
  resize: none;
  overflow: hidden;
  box-sizing: border-box;
  line-height: 1.4;
}
.poll-question:focus { border-color: var(--accent); outline: none; }

.poll-controls-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.poll-multi-label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  color: var(--text);
  font-size: 0.9rem;
  cursor: pointer;
}
#poll-start-btn { margin-left: auto; }

.poll-quick-section {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.poll-quick-label {
  font-size: 0.8rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.poll-quick-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}
.poll-quick-btn {
  font-size: 0.85rem;
  padding: 0.35rem 0.7rem;
}

/* ── Poll tab — center pane ───────────────────────────────────────── */
#center-poll { display: none; flex-direction: column; min-height: 0; }
.poll-center-title {
  margin: 0 0 0.9rem;
  font-size: 0.95rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.poll-options-container {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  overflow-y: auto;
  flex: 1 1 auto;
  min-height: 0;
  padding-right: 0.25rem;
}
.poll-option-row {
  width: 100%;
  min-height: 2.4rem;
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--surface2);
  color: var(--text);
  font-size: 0.95rem;
  font-family: inherit;
  resize: none;
  overflow: hidden;
  box-sizing: border-box;
  line-height: 1.4;
}
.poll-option-row.filled { border-color: var(--success); }
.poll-option-row:focus { outline: none; border-color: var(--accent); }

.poll-clear-btn {
  align-self: flex-start;
  margin-top: 0.75rem;
}
```

- [ ] **Step 2: Reload `http://localhost:8081/`, click the Poll tab, visually verify**

Expected: left pane is laid out cleanly (textarea, controls row with Start right-aligned, Quick Questions row of buttons). Center pane is still empty (no JS yet) but the title "👍 Poll Options" and Clear All button should be visible.

- [ ] **Step 3: Commit**

```bash
git add static/host.css
git commit -m "feat(poll): add CSS for poll composer (left + center)"
```

---

## Task 11: Implement poll composer JS — state, render, presets

**Files:**
- Modify: `static/host.js` (append a new IIFE near the end of the file, before the closing `})()` of the main IIFE if there is one — or as a module-local block alongside other composers)

- [ ] **Step 1: Find an appropriate insertion point**

Open `static/host.js` and locate the Quiz composer block starting around line 1530 (`// ── Quiz composer (contenteditable) ──`). The poll composer block should go directly after the Quiz composer's last related function (around line 1700, after `_resetBackstage` and friends). Find a stable anchor like a section comment or function boundary.

The safest anchor is just after `window.clearBackstage = function() { … };` (around line 1696–1700). Insert a new section comment to mark the start.

- [ ] **Step 2: Insert the poll composer skeleton**

Insert immediately after `window.clearBackstage = function() { … };` closes:

```javascript

  // ── Poll composer ──
  const POLL_PRESETS = {
    yesno:      { question: '', options: ['Yes', 'No'], multi: false },
    truefalse:  { question: '', options: ['True', 'False'], multi: false },
    rating15:   { question: '', options: ['1', '2', '3', '4', '5'], multi: false },
    energy:     { question: '', options: ['🔥 On fire', '😄 Energized', '😐 OK', '😴 Sleepy', '💀 Need coffee'], multi: false },
  };

  const pollState = {
    question: '',
    options: [''],
    multi: false,
  };

  const pollQuestionEl  = document.getElementById('poll-question');
  const pollMultiEl     = document.getElementById('poll-multi');
  const pollStartBtn    = document.getElementById('poll-start-btn');
  const pollClearBtn    = document.getElementById('poll-clear-btn');
  const pollOptionsEl   = document.getElementById('poll-options-container');
  const pollQuickBtns   = document.querySelectorAll('.poll-quick-btn');

  function autoGrow(el) {
    el.style.height = 'auto';
    el.style.height = el.scrollHeight + 'px';
  }

  function renderPoll() {
    pollQuestionEl.value = pollState.question;
    autoGrow(pollQuestionEl);
    pollMultiEl.checked = pollState.multi;
    pollOptionsEl.innerHTML = '';
    pollState.options.forEach((val, i) => {
      const row = document.createElement('textarea');
      row.className = 'poll-option-row' + (val.trim() ? ' filled' : '');
      row.rows = 1;
      row.value = val;
      row.placeholder = i === pollState.options.length - 1 ? 'Add option…' : '';
      row.addEventListener('input', () => onPollOptionInput(i, row));
      pollOptionsEl.appendChild(row);
      autoGrow(row);
    });
    updatePollStartEnabled();
  }

  function updatePollStartEnabled() {
    const validQ = pollState.question.trim() !== '';
    const nonEmpty = pollState.options.filter(s => s.trim() !== '').length;
    pollStartBtn.disabled = !(validQ && nonEmpty >= 2);
  }

  function applyPollPreset(name) {
    const preset = POLL_PRESETS[name];
    if (!preset) return;
    pollState.question = preset.question;
    pollState.options = [...preset.options, ''];   // trailing empty draft row
    pollState.multi = preset.multi;
    renderPoll();
    flushPollUpdate();  // immediate, no debounce
  }

  function resetPollLocal() {
    pollState.question = '';
    pollState.options = [''];
    pollState.multi = false;
    renderPoll();
  }

  // Stubs filled in by Task 12:
  function flushPollUpdate() { /* implemented in Task 12 */ }
  function onPollOptionInput(i, row) { /* implemented in Task 12 */ }

  // Initial render
  renderPoll();

  // Wire Quick Question buttons
  pollQuickBtns.forEach(btn => {
    btn.addEventListener('click', () => applyPollPreset(btn.dataset.preset));
  });
```

- [ ] **Step 3: Reload the host page, click Poll tab, click each Quick Questions button**

Expected: clicking "Yes / No" replaces the center pane options with `Yes`, `No`, and an empty draft row. Filled rows show bright green border, draft row dim. Multi checkbox state updates. Start button enables once you type a question. No backend calls yet — that's Task 12.

- [ ] **Step 4: Commit**

```bash
git add static/host.js
git commit -m "feat(poll): add poll composer state, render, and preset wiring"
```

---

## Task 12: Wire input events, debounce, and `/poll/update`

**Files:**
- Modify: `static/host.js` (extend the poll composer block from Task 11)

- [ ] **Step 1: Replace the stub `flushPollUpdate` and `onPollOptionInput` with real implementations**

In `static/host.js`, find the two stubs added in Task 11:

```javascript
  // Stubs filled in by Task 12:
  function flushPollUpdate() { /* implemented in Task 12 */ }
  function onPollOptionInput(i, row) { /* implemented in Task 12 */ }
```

Replace with:

```javascript
  let _pollUpdateTimer = null;

  function pollPayload() {
    return {
      question: pollState.question,
      options: pollState.options.map(s => s.trim()).filter(s => s !== ''),
      multi: pollState.multi,
    };
  }

  async function sendPollUpdate() {
    try {
      await fetch(API('/host/poll/update'), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pollPayload()),
      });
    } catch (e) {
      // Daemon may be momentarily unreachable; the next edit will retry.
    }
  }

  function flushPollUpdate() {
    if (_pollUpdateTimer) { clearTimeout(_pollUpdateTimer); _pollUpdateTimer = null; }
    sendPollUpdate();
  }

  function schedulePollUpdate() {
    if (_pollUpdateTimer) clearTimeout(_pollUpdateTimer);
    _pollUpdateTimer = setTimeout(() => { _pollUpdateTimer = null; sendPollUpdate(); }, 300);
  }

  function onPollOptionInput(i, row) {
    pollState.options[i] = row.value;
    row.classList.toggle('filled', row.value.trim() !== '');
    autoGrow(row);
    // Auto-spawn trailing draft row when the user types into the last (previously empty) row.
    const isLast = i === pollState.options.length - 1;
    if (isLast && row.value !== '') {
      pollState.options.push('');
      renderPoll();
      // After re-render, focus the row the user was typing in (still index i)
      const rows = pollOptionsEl.querySelectorAll('.poll-option-row');
      if (rows[i]) {
        rows[i].focus();
        const len = rows[i].value.length;
        rows[i].setSelectionRange(len, len);
      }
      flushPollUpdate();   // structural change → immediate
    } else {
      updatePollStartEnabled();
      schedulePollUpdate(); // text-only change → debounced
    }
  }
```

- [ ] **Step 2: Wire question textarea + multi checkbox events**

Locate the section in the poll composer (added in Task 11) just before the `// Initial render` line. Add these event wires above it:

```javascript
  pollQuestionEl.addEventListener('input', () => {
    pollState.question = pollQuestionEl.value;
    autoGrow(pollQuestionEl);
    updatePollStartEnabled();
    schedulePollUpdate();
  });

  pollMultiEl.addEventListener('change', () => {
    pollState.multi = pollMultiEl.checked;
    flushPollUpdate();   // toggle is structural → immediate
  });
```

- [ ] **Step 3: Verify in browser with daemon log monitoring**

Tail daemon log in one terminal:
```
tail -f logs/daemon.log | grep -i poll
```

Reload `http://localhost:8081/`, click Poll tab, type slowly in the question — observe one `poll/update` DEBUG line ~300ms after each idle pause. Toggle Multi — observe immediate `poll/update`. Click Yes/No preset — observe immediate `poll/update`. Add a third option by typing into the trailing row — observe immediate `poll/update` (structural).

- [ ] **Step 4: Commit**

```bash
git add static/host.js
git commit -m "feat(poll): wire input events with debounced /poll/update"
```

---

## Task 13: Wire Start button → `POST /poll/start`

**Files:**
- Modify: `static/host.js` (extend the poll composer block)

- [ ] **Step 1: Add the Start click handler**

In `static/host.js`, find the line at the end of the poll composer block:

```javascript
  // Initial render
  renderPoll();
```

Insert immediately ABOVE it:

```javascript
  pollStartBtn.addEventListener('click', async () => {
    if (pollStartBtn.disabled) return;
    flushPollUpdate();  // make sure backend has the latest before /start
    let res;
    try {
      res = await fetch(API('/host/poll/start'), { method: 'POST' });
    } catch (e) {
      toast('Network error — daemon unreachable');
      return;
    }
    if (res.ok) {
      toast('Poll started ✓');
    } else {
      const data = await res.json().catch(() => ({}));
      toast(data.error || 'Poll start failed');
    }
  });
```

- [ ] **Step 2: Verify in browser**

Reload, click Poll tab, fill in a question and at least 2 options, click Start. Expected:
- `poll/update` fires immediately (flush)
- `poll/start` fires next, gets 204
- Toast "Poll started ✓" shows
- Daemon log shows INFO line `◆ poll started: 'Q?' (2 options, multi=False)`
- Form stays populated (does not reset)

Click Start again — toast and 204 again (idempotent).

- [ ] **Step 3: Commit**

```bash
git add static/host.js
git commit -m "feat(poll): wire Start button to POST /poll/start"
```

---

## Task 14: Wire Clear All → `POST /poll/stop`

**Files:**
- Modify: `static/host.js` (extend the poll composer block)

- [ ] **Step 1: Add the Clear All click handler**

In `static/host.js`, insert immediately above the `// Initial render` line (after the Start button handler from Task 13):

```javascript
  pollClearBtn.addEventListener('click', async () => {
    // Cancel any pending debounced update — we're about to stop.
    if (_pollUpdateTimer) { clearTimeout(_pollUpdateTimer); _pollUpdateTimer = null; }
    resetPollLocal();
    try {
      await fetch(API('/host/poll/stop'), { method: 'POST' });
    } catch (e) {
      toast('Network error — daemon unreachable');
    }
  });
```

- [ ] **Step 2: Verify in browser**

With a poll started (from Task 13's verification), click Clear All. Expected:
- Form resets: question empty, one empty option row, Multi unchecked.
- Daemon log shows INFO line `◆ poll stopped`.
- Click Clear All again immediately — silent (idempotent), no toast, log says nothing (no INFO since `had_data` is False).

- [ ] **Step 3: Commit**

```bash
git add static/host.js
git commit -m "feat(poll): wire Clear All to POST /poll/stop + local reset"
```

---

## Task 15: Wire `updateCenterPanel` to show `#center-poll`

**Files:**
- Modify: `static/host.js:2100-2117` (`updateCenterPanel` function)

- [ ] **Step 1: Add 'poll' to the panel-toggle list**

In `static/host.js`, find `updateCenterPanel` (around line 2095) and locate:

```javascript
    ['qr', 'quiz', 'wordcloud', 'qa', 'debate', 'codereview'].forEach(id => {
      const el = document.getElementById('center-' + id);
      if (id === 'qr') {
        el.style.display = currentActivity === 'none' ? 'flex' : 'none';
      } else if (id === 'quiz') {
        // ... quiz-specific branch ...
      } else {
        const showVal = id === 'codereview' ? 'flex' : '';
        el.style.display = currentActivity === id ? showVal : 'none';
      }
    });
```

Replace the array literal `['qr', 'quiz', 'wordcloud', 'qa', 'debate', 'codereview']` with:

```javascript
    ['qr', 'quiz', 'poll', 'wordcloud', 'qa', 'debate', 'codereview'].forEach(id => {
```

(No new branch needed — poll falls through to the `else` branch, which sets `el.style.display = '' ` when `currentActivity === 'poll'`. The CSS `#center-poll { display: none; flex-direction: column; }` becomes `display: flex` implicitly via the empty string clearing the inline `none`. Verify in step 2.)

Actually, since `#center-poll`'s base CSS rule has `display: none`, the `display: ''` from inline-style removal would not flip it to flex. We need an explicit flex case. Update the `else` branch:

```javascript
      } else {
        const flexPanels = new Set(['codereview', 'poll']);
        const showVal = flexPanels.has(id) ? 'flex' : '';
        el.style.display = currentActivity === id ? showVal : 'none';
      }
```

- [ ] **Step 2: Verify in browser**

Reload, click between Slides → Quiz → Poll → Words tabs. Expected: when on Poll tab, the center pane shows the poll composer (title "👍 Poll Options", options container, Clear All). Other tabs do not show poll-center content. Switching back to Slides hides the poll center pane.

- [ ] **Step 3: Commit**

```bash
git add static/host.js
git commit -m "feat(poll): show center-poll panel when poll tab is active"
```

---

## Task 16: Full smoke test + final verification

**Files:** (no edits — verification only)

- [ ] **Step 1: Run the full daemon test suite**

Run: `bash tests/run-daemon-tests.sh`

Expected: All tests PASS, including new `tests/daemon/poll/test_poll_router.py` (11 tests) and unchanged contract tests.

- [ ] **Step 2: Manual smoke test in browser**

With daemon running, open `http://localhost:8081/`, click Poll tab, exercise:

1. Type into option row 1 → new empty row spawns; row 1 border turns green.
2. Type into the new last row → another empty row spawns.
3. Delete all text from a middle row → row stays in place, border dims.
4. Enter a question, ensure ≥2 filled options → Start button enables.
5. Toggle Multi on/off → check `logs/daemon.log` for immediate `poll/update`.
6. Click each preset (Yes/No, True/False, 1–5, Energy Level) → form fills correctly, `poll/update` fires immediately each time.
7. Click Start → toast "Poll started ✓", form stays populated, log shows `◆ poll started`.
8. Edit a few keystrokes after Start → `poll/update` continues to fire (debounced).
9. Click Clear All → form resets to one empty option, Multi off, question empty; log shows `◆ poll stopped`.

- [ ] **Step 3: Take a screenshot of the populated Poll tab**

Per the project CLAUDE.md ("After any visual/UI change, always show a screenshot to the user as proof"):
- Open Poll tab, click "Energy Level" preset, type "How's the room?" in the question.
- Take a screenshot (browser screenshot tool or system screenshot) of the host UI showing left + center panes populated.
- Save as `logs/poll-tab-smoke.png` (gitignored).

- [ ] **Step 4: Run the pre-commit hook parity check**

Run: `uv run --extra dev --extra daemon bash tests/check-all.sh`

Expected: All checks PASS.

- [ ] **Step 5: Push to master**

```bash
git push origin master
```

Per CLAUDE.md: small changes go directly to master, no PR.

- [ ] **Step 6: Wait for prod deploy + verify**

After ~40–50s Railway redeploys.

Verify a poll endpoint exists on prod (will return 401 without basic auth, but that confirms routing):
```
curl -s -o /dev/null -w "%{http_code}\n" -X PUT https://interact.victorrentea.ro/api/anything/host/poll/update
```
Expected: `401` (auth challenge — route is wired, just no creds). Anything else (e.g., `404`) means the deploy hasn't picked up yet — wait and retry.

For full verification with auth, hit it from the host page in a browser; or use the wait-for-deploy skill.

---

## Self-Review

Spec coverage check:

| Spec section | Covered by task(s) |
|---|---|
| §2.1 Left pane (question, Start, Multi, Quick Questions) | Tasks 8, 10, 11, 12, 13 |
| §2.2 Center pane (dynamic option rows, auto-spawn, contrast borders, middle-empty preserved, Clear All, overflow scroll) | Tasks 9, 10, 11, 12, 14 |
| §3 Backend endpoint table (debounced PUT, immediate PUT, Start flush, Clear cancel) | Tasks 3, 4, 5, 12, 13, 14 |
| §3.2 PollData Pydantic model | Task 1 |
| §3.3 PollState singleton | Task 1 |
| §3.4 Endpoint semantics (update accepts incomplete, start validates, stop is idempotent) | Tasks 3, 4, 5 (with explicit tests for each rule) |
| §3.5 Router registration | Task 6 |
| §3.6 OpenAPI + API.md regeneration | Task 7 |
| §4 Client-side state model (auto-grow, render, mutations, payload trim/filter, switchTab wiring) | Tasks 11, 12, 13, 14, 15 |
| §5 Files touched | All tasks (matches file table) |
| §6 Out of scope (no participant, no WS, no activity-state change beyond what `switchTab` already does) | Honored — no new participant/WS code in any task |
| §7 Testing (smoke + contract snapshot) | Tasks 7, 16 |
| §8 Question-required rule | Task 4 (`test_start_with_empty_question_returns_409`) + Task 11 (`updatePollStartEnabled` includes `validQ`) |

No placeholders or TBD references in any step. No "similar to Task N" — every step has its own complete code block. Type/name consistency verified: `pollState`, `pollPayload`, `flushPollUpdate`, `schedulePollUpdate`, `applyPollPreset`, `resetPollLocal`, `onPollOptionInput`, `autoGrow`, `updatePollStartEnabled` — all defined where first referenced, used consistently. Backend names (`PollData`, `PollState`, `poll_state`, `host_router`) match between `daemon/poll/state.py`, `daemon/poll/router.py`, `daemon/host_server.py`, and the test fixtures.
