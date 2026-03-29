# Session ID in URL Path — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the active session_id in the host URL (`/host/{session_id}`) and participant URL (`/{session_id}`), replace the session blocker with a folder-list picker, and add a Stop button that returns the host to the landing page.

**Architecture:** The branch already has the participant side wired (`/{session_id}/*` routes, `WS /ws/{session_id}/{uuid}`). This plan completes the host side: backend endpoint for `GET /host/{session_id}`, backend fixes for session create/end, and frontend changes to the blocker overlay and stop button.

**Tech Stack:** FastAPI, Python 3.12, Vanilla JS, plain HTML.

---

## Already Done (Do NOT Redo)

- `core/state.py` — `session_id: str | None` + `generate_session_id()`
- `core/session_guard.py` — `require_valid_session` dependency
- `features/ws/router.py` — `WS /ws/{session_id}/{participant_id}` (session-scoped)
- `main.py` — `session_participant` router: `/{session_id}` prefix for participant-facing routes
- `features/session/router.py` — all session lifecycle endpoints

---

## File Map

| File | Change |
|------|--------|
| `features/session/router.py` | Fix `get_session_active` (return `session_id`); fix `create_session` (return `session_id`, broadcast); fix `end_session` (clear `state.session_id`, broadcast); make `list_session_folders` public |
| `features/pages/router.py` | Add `GET /host/{session_id}` route |
| `static/host.html` | Replace blocker text-only UI with folder list + new-session input; add Stop badge to footer |
| `static/host.js` | Update `blockerStart` (pushState after create); `_updateBlocker` (URL-based auto-dismiss + folder list loading); new `stopSession()`; new `_loadBlockerFolderList()`; new `_getSessionIdFromUrl()` |
| `tests/unit/test_session_endpoints.py` | New: unit tests for all backend fixes |

---

## Task 1: Backend — Fix `GET /api/session/active` to expose session_id

**Files:**
- Modify: `features/session/router.py` (last function)
- Test: `tests/unit/test_session_endpoints.py` (new file)

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_session_endpoints.py
import base64
import pytest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from main import app
from core.state import state

client = TestClient(app)

HOST_AUTH = {"Authorization": "Basic " + base64.b64encode(b"host:host").decode()}

@pytest.fixture(autouse=True)
def reset_session_id():
    old = state.session_id
    state.session_id = None
    yield
    state.session_id = old


def test_session_active_returns_false_and_null_when_no_session():
    response = client.get("/api/session/active")
    assert response.status_code == 200
    body = response.json()
    assert body == {"active": False, "session_id": None}


def test_session_active_returns_true_and_id_when_active():
    state.session_id = "abc123"
    response = client.get("/api/session/active")
    body = response.json()
    assert body == {"active": True, "session_id": "abc123"}
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m pytest tests/unit/test_session_endpoints.py::test_session_active_returns_false_and_null_when_no_session -xvs
```
Expected: FAIL — response body lacks `session_id`

- [ ] **Step 3: Fix the endpoint**

In `features/session/router.py`, replace the last function:
```python
@router.get("/api/session/active")
async def get_session_active():
    """Public endpoint: returns whether a session is active and its ID."""
    return {"active": state.session_id is not None, "session_id": state.session_id}
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
python3 -m pytest tests/unit/test_session_endpoints.py -xvs
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add features/session/router.py tests/unit/test_session_endpoints.py
git commit -m "feat(session): expose session_id in /api/session/active response"
```

---

## Task 2: Backend — `POST /api/session/create` returns session_id + broadcasts

**Files:**
- Modify: `features/session/router.py` (`create_session`)
- Test: `tests/unit/test_session_endpoints.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_session_endpoints.py`:
```python
def test_session_create_returns_session_id_and_updates_state(monkeypatch):
    import features.session.router as sr
    monkeypatch.setattr(sr, "push_to_daemon", AsyncMock())
    monkeypatch.setattr(sr, "broadcast_state", AsyncMock())
    response = client.post("/api/session/create", json={"name": "2026-03-29 WS"},
                           headers=HOST_AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "session_id" in body
    assert len(body["session_id"]) == 6
    assert state.session_id == body["session_id"]
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m pytest tests/unit/test_session_endpoints.py::test_session_create_returns_session_id_and_updates_state -xvs
```
Expected: FAIL — response body lacks `session_id`

- [ ] **Step 3: Fix `create_session`**

In `features/session/router.py`, replace `create_session`:
```python
@router.post("/api/session/create", dependencies=[Depends(require_host_auth)])
async def create_session(body: SessionNameBody):
    session_id = state.generate_session_id()  # always generate fresh
    state.session_request = {"action": "create", "name": body.name, "session_id": session_id}
    await push_to_daemon({"type": "session_request", **state.session_request})
    await broadcast_state()
    return {"ok": True, "session_id": session_id}
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/unit/test_session_endpoints.py -xvs
```
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add features/session/router.py tests/unit/test_session_endpoints.py
git commit -m "feat(session): create_session returns session_id and broadcasts state"
```

---

## Task 3: Backend — `POST /api/session/end` clears session_id + broadcasts

**Files:**
- Modify: `features/session/router.py` (`end_session`)
- Test: `tests/unit/test_session_endpoints.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_session_endpoints.py`:
```python
def test_session_end_clears_session_id(monkeypatch):
    import features.session.router as sr
    monkeypatch.setattr(sr, "push_to_daemon", AsyncMock())
    monkeypatch.setattr(sr, "broadcast_state", AsyncMock())
    state.session_id = "alive123"
    response = client.post("/api/session/end", headers=HOST_AUTH)
    assert response.status_code == 200
    assert state.session_id is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m pytest tests/unit/test_session_endpoints.py::test_session_end_clears_session_id -xvs
```
Expected: FAIL — `state.session_id` still set after end

- [ ] **Step 3: Fix `end_session`**

In `features/session/router.py`, replace `end_session`:
```python
@router.post("/api/session/end", dependencies=[Depends(require_host_auth)])
async def end_session():
    state.session_request = {"action": "end"}
    state.session_id = None  # immediately revoke session — blocks new participant connections
    await push_to_daemon({"type": "session_request", **state.session_request})
    await broadcast_state()
    return {"ok": True}
```

- [ ] **Step 4: Run all session endpoint tests**

```bash
python3 -m pytest tests/unit/test_session_endpoints.py -xvs
```
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add features/session/router.py tests/unit/test_session_endpoints.py
git commit -m "feat(session): end_session clears session_id immediately and broadcasts"
```

---

## Task 4: Backend — `GET /host/{session_id}` serves host.html + make `list_session_folders` public

**Files:**
- Modify: `features/pages/router.py`
- Modify: `features/session/router.py` (`list_session_folders` — remove auth)
- Test: `tests/unit/test_session_endpoints.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_session_endpoints.py`:
```python
def test_host_session_page_requires_auth():
    response = client.get("/host/abc123")
    assert response.status_code == 401


def test_host_session_page_serves_html_when_authed():
    response = client.get("/host/abc123", headers=HOST_AUTH)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_session_folders_is_public():
    """Folders endpoint must be public so the browser-side blocker JS can call it."""
    response = client.get("/api/session/folders")
    assert response.status_code == 200
    assert "folders" in response.json()
```

- [ ] **Step 2: Run to confirm failures**

```bash
python3 -m pytest tests/unit/test_session_endpoints.py::test_host_session_page_requires_auth tests/unit/test_session_endpoints.py::test_session_folders_is_public -xvs
```
Expected: FAIL on both

- [ ] **Step 3: Add host session page route**

In `features/pages/router.py`, add below the `/host` route:
```python
@host_router.get("/host/{session_id}", response_class=HTMLResponse, dependencies=[Depends(require_host_auth)])
async def host_session_page(session_id: str):
    """Serve host panel for a specific session. Session validation is handled client-side."""
    response = FileResponse("static/host.html")
    response.set_cookie("is_host", "1", path="/", samesite="strict")
    return response
```

- [ ] **Step 4: Make `list_session_folders` public**

In `features/session/router.py`, find the `list_session_folders` function and remove `dependencies=[Depends(require_host_auth)]`:
```python
@router.get("/api/session/folders")  # public — folder names are not sensitive
async def list_session_folders():
    root = _get_sessions_root()
    folders = []
    if root:
        folders = sorted([f.name for f in root.iterdir() if f.is_dir()], reverse=True)
    return {"folders": folders}
```

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/unit/test_session_endpoints.py -xvs
```
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add features/pages/router.py features/session/router.py tests/unit/test_session_endpoints.py
git commit -m "feat(pages): add GET /host/{session_id} route; make session/folders endpoint public"
```

---

## Task 5: Frontend — Blocker shows folder list + redirects to `/host/{session_id}` after create

**Files:**
- Modify: `static/host.html` (blocker HTML section)
- Modify: `static/host.js` (`_updateBlocker`, `blockerStart`, `onBlockerInput`, new helpers)

### 5a. HTML changes

- [ ] **Step 1: Replace the blocker HTML section in `static/host.html`**

Find the section `<!-- Session blocker: gates host UI until a session is active -->` through its closing `</div>` (the line just before `<div class="host-layout">`), and replace it entirely with:

```html
<!-- Session blocker: gates host UI until a session is active -->
<div id="session-blocker" style="position:fixed; inset:0; z-index:99999; background:var(--bg); display:flex; align-items:center; justify-content:center; flex-direction:column; gap:1rem;">
  <div style="font-size:1.6rem; font-weight:700; color:var(--accent); margin-bottom:.3rem;">Host Panel</div>

  <!-- Existing session folders -->
  <div id="blocker-folder-list" style="display:flex; flex-direction:column; gap:.35rem; max-height:220px; overflow-y:auto; width:340px;"></div>

  <!-- New session row -->
  <div style="display:flex; align-items:center; gap:.5rem; margin-top:.4rem;">
    <input id="blocker-session-input" type="text" placeholder="New session name…" autocomplete="off"
           style="font-size:1rem; padding:.5rem .75rem; border-radius:var(--radius); border:2px solid var(--border); background:var(--surface2); color:var(--text); width:250px; outline:none; transition:border-color .15s;"
           oninput="onBlockerInput()"
           onkeydown="if(event.key==='Enter' && !document.getElementById('blocker-start-btn').disabled) blockerStart();" />
    <button id="blocker-start-btn" disabled onclick="blockerStart()"
            style="padding:.5rem 1.1rem; font-size:1rem; font-weight:700; border:none; border-radius:var(--radius); background:var(--accent); color:#fff; cursor:pointer; transition:filter .15s;">
      Start
    </button>
  </div>
  <div id="blocker-status" style="color:var(--muted); font-size:.8rem; min-height:1.2em;"></div>
  <div id="blocker-version-tag" style="font-size:.7rem; color:var(--muted); margin-top:.2rem;"></div>
</div>
```

### 5b. JS changes

- [ ] **Step 2: Add two new helper functions in `host.js`** (near the session management section ~line 2982):

```javascript
function _getSessionIdFromUrl() {
  const m = location.pathname.match(/^\/host\/([a-z0-9]+)$/i);
  return m ? m[1].toLowerCase() : null;
}

function _loadBlockerFolderList() {
  fetch('/api/session/folders')
    .then(r => r.json())
    .then(data => {
      const list = document.getElementById('blocker-folder-list');
      if (!list) return;
      list.innerHTML = '';
      const folders = data.folders || [];
      if (!folders.length) {
        list.innerHTML = '<div style="color:var(--muted); font-size:.85rem; text-align:center; padding:.5rem;">No past sessions</div>';
        return;
      }
      folders.forEach(name => {
        const item = document.createElement('div');
        item.textContent = name;
        item.style.cssText = 'padding:.45rem .75rem; border-radius:var(--radius); background:var(--surface2); color:var(--text); cursor:pointer; font-size:.95rem; transition:background .12s; border:1px solid var(--border);';
        item.onmouseenter = () => { item.style.background = 'var(--accent)'; item.style.color = '#fff'; };
        item.onmouseleave = () => { item.style.background = 'var(--surface2)'; item.style.color = 'var(--text)'; };
        item.onclick = () => {
          const input = document.getElementById('blocker-session-input');
          if (input) { input.value = name; onBlockerInput(); }
        };
        list.appendChild(item);
      });
    })
    .catch(() => {});
}
```

- [ ] **Step 3: Replace `_updateBlocker()`**

Find the entire `function _updateBlocker() { ... }` block and replace:
```javascript
function _updateBlocker() {
  const blocker = document.getElementById('session-blocker');
  if (!blocker) return;

  // Dismiss if host explicitly started a session via blockerStart()
  if (_blockerDismissed) {
    blocker.style.display = 'none';
    return;
  }

  // Auto-dismiss if URL already contains the active session_id (e.g. page reload on /host/{id})
  const urlSessionId = _getSessionIdFromUrl();
  if (urlSessionId && _currentSessionId && urlSessionId === _currentSessionId) {
    blocker.style.display = 'none';
    return;
  }

  blocker.style.display = 'flex';
  _loadBlockerFolderList();
}
```

- [ ] **Step 4: Replace `blockerStart()`**

Find the entire `function blockerStart() { ... }` block and replace:
```javascript
function blockerStart() {
  const input = document.getElementById('blocker-session-input');
  const name = input.value.trim();
  if (!name) return;

  const btn = document.getElementById('blocker-start-btn');
  const statusEl = document.getElementById('blocker-status');
  if (btn) btn.disabled = true;
  if (statusEl) statusEl.textContent = 'Starting session\u2026';

  fetch('/api/session/create', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name})
  })
    .then(r => r.json())
    .then(data => {
      if (data.session_id) {
        history.pushState(null, '', `/host/${data.session_id}`);
        _blockerDismissed = true;
        _updateBlocker();
      } else {
        if (statusEl) statusEl.textContent = 'Failed to start session.';
        if (btn) btn.disabled = false;
      }
    })
    .catch(e => {
      console.error('blockerStart failed:', e);
      if (statusEl) statusEl.textContent = 'Error \u2014 check console.';
      if (btn) btn.disabled = !input.value.trim();
    });
}
```

- [ ] **Step 5: Replace `onBlockerInput()`**

Find the entire `function onBlockerInput() { ... }` block and replace:
```javascript
function onBlockerInput() {
  const input = document.getElementById('blocker-session-input');
  const btn = document.getElementById('blocker-start-btn');
  if (input && btn) btn.disabled = !input.value.trim();
}
```

- [ ] **Step 6: Remove dead functions and clean up initialization**

Delete these now-unused standalone functions from `host.js`:
- `function _startBlockerAutoStart() { ... }` (including its body)
- `function _clearBlockerAutoStart() { ... }` (including its body)

Find the bottom-of-file initialization block:
```javascript
// Initialize blocker with date pre-fill on page load
_updateBlocker();
setTimeout(() => {
  const input = document.getElementById('blocker-session-input');
  if (input && document.getElementById('session-blocker').style.display !== 'none') input.focus();
}, 100);
```
Replace with:
```javascript
_updateBlocker();
```

The variable declarations `_blockerAutoTimer`, `_blockerFolderExists`, `_blockerOriginalName` at the top of the file can be left in place — they are harmless dead code.

- [ ] **Step 7: Verify JS syntax**

```bash
node --check static/host.js
```
Expected: no output (clean parse)

- [ ] **Step 8: Commit**

```bash
git add static/host.html static/host.js
git commit -m "feat(host): folder-list blocker picker with URL redirect to /host/{session_id}"
```

---

## Task 6: Frontend — Stop button in host footer

**Files:**
- Modify: `static/host.html` (footer)
- Modify: `static/host.js` (new `stopSession` + update `updateSessionCodeBar`)

- [ ] **Step 1: Add Stop badge to footer in `host.html`**

In `static/host.html`, find `<div class="host-footer-right">` and add as its **first child**:
```html
<span id="stop-session-btn" class="badge" title="Stop session and return to landing"
      onclick="stopSession()" style="cursor:pointer; display:none; color:var(--danger, #f66);">⏹</span>
```

- [ ] **Step 2: Add `stopSession` function to `host.js`** (near `blockerStart`):

```javascript
function stopSession() {
  if (!_currentSessionId) return;
  if (!confirm('Stop this session and return to the host landing page?')) return;
  fetch('/api/session/end', {method: 'POST'})
    .then(() => { location.href = '/host'; })
    .catch(e => console.error('stopSession failed:', e));
}
```

- [ ] **Step 3: Show/hide stop button in `updateSessionCodeBar`**

In `updateSessionCodeBar(sessionId)`, immediately after `_currentSessionId = sessionId;`, add:
```javascript
const stopBtn = document.getElementById('stop-session-btn');
if (stopBtn) stopBtn.style.display = sessionId ? '' : 'none';
```

- [ ] **Step 4: Verify JS syntax**

```bash
node --check static/host.js
```

- [ ] **Step 5: Commit**

```bash
git add static/host.html static/host.js
git commit -m "feat(host): add stop-session button to footer"
```

---

## Task 7: Full test suite + smoke test

- [ ] **Step 1: Run all unit tests**

```bash
python3 -m pytest tests/unit/ -q
```
Expected: all pass. The 3 pre-existing failures in `tests/daemon/test_daemon_state.py` are unrelated — verify the failure count has NOT increased.

- [ ] **Step 2: Run daemon tests**

```bash
python3 -m pytest tests/daemon/ -q
```
Expected: same 3 pre-existing failures only.

- [ ] **Step 3: Run integration tests if any**

```bash
python3 -m pytest tests/integration/ -q 2>/dev/null || echo "No integration tests"
```

- [ ] **Step 4: Smoke test — session lifecycle**

```bash
python3 -m uvicorn main:app --port 8001 &
sleep 2

# No active session
curl -s http://localhost:8001/api/session/active
# Expected: {"active":false,"session_id":null}

# Folders endpoint is public
curl -s http://localhost:8001/api/session/folders
# Expected: {"folders":[...]} with 200 status (no auth needed)

# Host session page
curl -si -u host:host http://localhost:8001/host/abc123 | head -3
# Expected: HTTP/1.1 200 OK, content-type: text/html

kill %1
```

- [ ] **Step 5: Rebase and push**

```bash
git fetch origin
git rebase origin/master
git push origin victorrentea/session-id-in-path
```

---

## Notes for Implementer

- **Auth credentials** for tests: `HOST_USERNAME` / `HOST_PASSWORD` default to `"host"/"host"` when env vars are unset — `b"host:host"` in `HOST_AUTH` is correct for local testing without the secrets file.
- **`push_to_daemon` and `broadcast_state` are both `async`** — always use `AsyncMock` when monkeypatching them in pytest tests.
- **3 pre-existing test failures** in `tests/daemon/test_daemon_state.py` (`test_parse_powerpoint_probe_output_*`) are unrelated to this feature. Do not attempt to fix them.
- **`_loadBlockerFolderList` calls `GET /api/session/folders`** — Task 4 makes this endpoint public so the browser JS can call it without Basic Auth credentials (which JS fetches don't send by default).
