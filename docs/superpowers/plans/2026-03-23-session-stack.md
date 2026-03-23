# Session Stack & Progressive Summarization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace flat session model with a stacked session system where each session has its own folder, key points, and transcript time window.

**Architecture:** Daemon owns session state (stack + folders + key_points.json), syncs to server via long-polling. Host sends session commands as pending requests. Server mirrors state for WebSocket broadcast. Replaces existing locked/draft summary model with flat key points + watermark.

**Tech Stack:** Python/FastAPI backend, vanilla JS frontend, Claude API for summarization.

**Spec:** `docs/superpowers/specs/2026-03-23-session-stack-design.md`

**Testing pattern:** This codebase uses `TestClient(app)` directly with `_HOST_AUTH_HEADERS` dict for auth. No pytest fixtures — all tests create their own `TestClient`. See existing standalone tests at the bottom of `tests/test_main.py` for the pattern.

---

### Task 1: Backend State & Session Router

**Files:**
- Modify: `state.py:71-74` (add session fields)
- Create: `routers/session.py`
- Modify: `main.py` (mount new router)
- Test: `tests/test_main.py`

- [ ] **Step 1: Write failing tests for session endpoints**

```python
# In tests/test_main.py — add at the end
# Uses the same pattern as existing standalone tests: TestClient(app) + _HOST_AUTH_HEADERS

def test_start_session_stores_request():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/session/start", json={"name": "2026-03-23 Workshop"}, headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["ok"]

def test_start_session_requires_auth():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/session/start", json={"name": "Test"})
    assert resp.status_code == 401

def test_end_session_stores_request():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/session/end", headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200

def test_rename_session_stores_request():
    state.reset()
    client = TestClient(app)
    resp = client.patch("/api/session/rename", json={"name": "New Name"}, headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200

def test_poll_session_request_returns_and_clears():
    state.reset()
    client = TestClient(app)
    # Store a request first
    client.post("/api/session/start", json={"name": "Test"}, headers=_HOST_AUTH_HEADERS)
    # Daemon polls it
    resp = client.get("/api/session/request", headers=_HOST_AUTH_HEADERS)
    assert resp.json()["action"] == "start"
    assert resp.json()["name"] == "Test"
    # Second poll should be empty (cleared after first read)
    resp2 = client.get("/api/session/request", headers=_HOST_AUTH_HEADERS)
    assert resp2.json()["action"] is None

def test_sync_session_updates_state():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/session/sync", json={
        "stack": [{"name": "Workshop", "started_at": "2026-03-23T09:00:00", "ended_at": None}],
        "key_points": [{"text": "Point 1", "source": "discussion"}],
    }, headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    assert len(state.session_stack) == 1
    assert len(state.summary_points) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_main.py::test_start_session_stores_request tests/test_main.py::test_sync_session_updates_state -v`
Expected: FAIL (404 / endpoints don't exist)

- [ ] **Step 3: Add session fields to AppState**

In `state.py`, after the `summary_force_full_day` line, add:

```python
        self.session_stack: list[dict] = []  # mirrors daemon's stack for broadcast
        self.session_request: dict | None = None  # pending host command for daemon
```

- [ ] **Step 4: Create routers/session.py**

```python
"""Session stack management — host commands + daemon sync."""

import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import require_host
from state import state
from messaging import broadcast_state

router = APIRouter()


def _get_sessions_root() -> Path | None:
    """Resolve the sessions root directory from env, same as quiz_core.find_session_folder."""
    sessions_root_str = os.environ.get(
        "SESSIONS_FOLDER",
        str(Path.home() / "My Drive" / "Cursuri" / "###sesiuni"),
    )
    p = Path(sessions_root_str).expanduser()
    return p if p.exists() and p.is_dir() else None


class StartSessionRequest(BaseModel):
    name: str


class RenameSessionRequest(BaseModel):
    name: str


class SyncSessionRequest(BaseModel):
    stack: list[dict]
    key_points: list[dict]


@router.post("/api/session/start")
async def start_session(body: StartSessionRequest, _=Depends(require_host)):
    state.session_request = {"action": "start", "name": body.name}
    return {"ok": True}


@router.post("/api/session/end")
async def end_session(_=Depends(require_host)):
    state.session_request = {"action": "end"}
    return {"ok": True}


@router.patch("/api/session/rename")
async def rename_session(body: RenameSessionRequest, _=Depends(require_host)):
    state.session_request = {"action": "rename", "name": body.name}
    return {"ok": True}


@router.get("/api/session/request")
async def poll_session_request(_=Depends(require_host)):
    req = state.session_request
    state.session_request = None
    if req:
        return req
    return {"action": None}


@router.post("/api/session/sync")
async def sync_session(body: SyncSessionRequest, _=Depends(require_host)):
    state.session_stack = body.stack
    state.summary_points = body.key_points
    state.summary_updated_at = datetime.now()
    await broadcast_state()
    return {"ok": True}


@router.get("/api/session/folders")
async def list_session_folders(_=Depends(require_host)):
    root = _get_sessions_root()
    folders = []
    if root:
        folders = sorted([f.name for f in root.iterdir() if f.is_dir()], reverse=True)
    return {"folders": folders}
```

- [ ] **Step 5: Mount the session router in main.py**

In `main.py`, follow the existing pattern for including routers. Add:
```python
from routers.session import router as session_router
app.include_router(session_router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_main.py -k "session" -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add state.py routers/session.py main.py tests/test_main.py
git commit -m "feat: session stack endpoints (start/end/rename/sync/poll)"
```

---

### Task 2: Broadcast Session Stack to Clients

**Files:**
- Modify: `messaging.py` (add session_stack to both broadcast functions, after `summary_updated_at`)
- Modify: `static/host.js` (receive session state)

- [ ] **Step 1: Add session_stack to broadcast payloads**

In `messaging.py`, in both `build_participant_state()` and `build_host_state()`, add after the `summary_updated_at` field:

```python
"session_stack": [{"name": s["name"], "started_at": s.get("started_at")} for s in state.session_stack],
"session_name": state.session_stack[-1]["name"] if state.session_stack else None,
```

- [ ] **Step 2: Receive session state in host.js**

In `host.js`, add state variables near line 14 (after `summaryUpdatedAt`):
```javascript
let sessionStack = [];
let sessionName = null;
```

In the WebSocket message handler where `updateSummary` is called, add:
```javascript
if (msg.session_stack !== undefined) {
  sessionStack = msg.session_stack || [];
  sessionName = msg.session_name || null;
  renderSessionPanel();
}
```

- [ ] **Step 3: Commit**

```bash
git add messaging.py static/host.js
git commit -m "feat: broadcast session stack to clients"
```

---

### Task 3: Host UI — Session Management Panel

**Files:**
- Modify: `static/host.html` (add session panel HTML inside `host-col-right`, after `right-footer` div)
- Modify: `static/host.js` (add session management functions)
- Modify: `static/host.css` (session panel styles)

**Note:** The exact insertion point in host.html must be verified by reading the file. Look for the closing `</div>` of `right-footer`, then the closing `</div>` of `host-col-right`. The session panel goes between them.

- [ ] **Step 1: Add session panel HTML**

Read `host.html` to find the exact insertion point. Insert this block inside `host-col-right`, after the `right-footer` div closes:

```html
    <div class="session-panel" id="session-panel">
      <div class="session-breadcrumb" id="session-breadcrumb"></div>
      <div class="session-current">
        <span class="session-label" id="session-name-label">No active session</span>
        <span class="session-edit-icon" id="session-edit-icon" onclick="renameSession()" title="Rename session" style="display:none;">✏️</span>
      </div>
      <div class="session-actions">
        <button class="btn btn-sm" id="btn-start-session" onclick="startNewSession()">▶ Start Session</button>
        <button class="btn btn-sm btn-danger" id="btn-end-session" onclick="endCurrentSession()" style="display:none;">■ End Session</button>
      </div>
    </div>
```

- [ ] **Step 2: Add session panel CSS**

In `host.css`, add:

```css
.session-panel {
  padding: .75rem 1rem;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: .4rem;
}
.session-breadcrumb {
  font-size: .7rem;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-current {
  display: flex;
  align-items: center;
  gap: .4rem;
}
.session-label {
  font-size: .85rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.session-edit-icon {
  cursor: pointer;
  font-size: .75rem;
  opacity: .6;
  flex-shrink: 0;
}
.session-edit-icon:hover { opacity: 1; }
.session-actions {
  display: flex;
  gap: .5rem;
}
.btn-sm {
  font-size: .7rem;
  padding: .2rem .6rem;
}
```

- [ ] **Step 3: Add session management JS functions**

In `host.js`, add:

```javascript
function renderSessionPanel() {
  const label = document.getElementById('session-name-label');
  const editIcon = document.getElementById('session-edit-icon');
  const breadcrumb = document.getElementById('session-breadcrumb');
  const btnStart = document.getElementById('btn-start-session');
  const btnEnd = document.getElementById('btn-end-session');
  if (!label) return;

  if (sessionStack.length === 0) {
    label.textContent = 'No active session';
    editIcon.style.display = 'none';
    breadcrumb.textContent = '';
    btnEnd.style.display = 'none';
    btnStart.disabled = false;
  } else {
    label.textContent = sessionName || 'Unnamed';
    editIcon.style.display = '';
    btnEnd.style.display = sessionStack.length > 1 ? '' : 'none';
    btnStart.disabled = sessionStack.length >= 3;

    if (sessionStack.length > 1) {
      breadcrumb.textContent = sessionStack.slice(0, -1).map(s => s.name).join(' > ');
    } else {
      breadcrumb.textContent = '';
    }
  }
}

async function startNewSession() {
  // Fetch folder suggestions for autocomplete
  let suggestions = [];
  try {
    const resp = await fetch('/api/session/folders');
    if (resp.ok) suggestions = (await resp.json()).folders || [];
  } catch (_) {}

  const defaultName = new Date().toISOString().slice(0, 10);
  const hint = suggestions.length ? '\n\nExisting folders:\n' + suggestions.slice(0, 10).join('\n') : '';
  const name = prompt('Session name (must match folder for notes):' + hint, defaultName);
  if (!name || !name.trim()) return;
  fetch('/api/session/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: name.trim() }),
  });
}

function endCurrentSession() {
  if (!confirm('End current session and return to previous?')) return;
  fetch('/api/session/end', { method: 'POST' });
}

function renameSession() {
  const current = sessionName || '';
  const name = prompt('Rename session:', current);
  if (!name || !name.trim() || name.trim() === current) return;
  fetch('/api/session/rename', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: name.trim() }),
  });
}
```

- [ ] **Step 4: Verify in browser**

Open http://localhost:8000/host — check that the session panel appears below the participant list with "No active session" and a "Start Session" button. Take a screenshot.

- [ ] **Step 5: Commit**

```bash
git add static/host.html static/host.js static/host.css
git commit -m "feat: host UI session management panel"
```

---

### Task 4: Daemon — Session Persistence Functions

**Files:**
- Modify: `training_daemon.py` (replace `_load_summary_cache`/`_save_summary_cache` with `_load_key_points`/`_save_key_points` + `_load_daemon_state`/`_save_daemon_state`)
- Test: `tests/test_daemon.py`

- [ ] **Step 1: Write tests for session persistence**

In `tests/test_daemon.py`, add:

```python
from training_daemon import _load_key_points, _save_key_points, _load_daemon_state, _save_daemon_state


class TestSessionKeyPoints:
    def test_load_from_empty_folder(self, tmp_path):
        assert _load_key_points(tmp_path) == []

    def test_save_and_load_roundtrip(self, tmp_path):
        points = [{"text": "P1", "source": "discussion", "time": "10:15"}]
        _save_key_points(tmp_path, points)
        loaded = _load_key_points(tmp_path)
        assert loaded == points

    def test_backward_compat_loads_locked_draft(self, tmp_path):
        """Test migration from old summary_cache.json format."""
        cache = tmp_path / "key_points.json"
        cache.write_text('{"locked": [{"text": "L1"}], "draft": [{"text": "D1"}]}')
        loaded = _load_key_points(tmp_path)
        assert len(loaded) == 2

    def test_load_daemon_state(self, tmp_path):
        state_file = tmp_path / "daemon_state.json"
        state_file.write_text('{"stack": [{"name": "Test", "started_at": "2026-03-23T09:00:00", "ended_at": null, "summary_watermark": 0}]}')
        stack = _load_daemon_state(tmp_path)
        assert len(stack) == 1
        assert stack[0]["name"] == "Test"

    def test_load_daemon_state_missing(self, tmp_path):
        assert _load_daemon_state(tmp_path) == []

    def test_save_daemon_state_roundtrip(self, tmp_path):
        stack = [{"name": "W", "started_at": "2026-03-23T09:00:00", "ended_at": None, "summary_watermark": 42}]
        _save_daemon_state(tmp_path, stack)
        loaded = _load_daemon_state(tmp_path)
        assert loaded == stack
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_daemon.py::TestSessionKeyPoints -v`
Expected: FAIL (ImportError — functions don't exist yet)

- [ ] **Step 3: Replace summary cache functions**

In `training_daemon.py`, replace `_load_summary_cache` and `_save_summary_cache` with:

```python
_KEY_POINTS_FILENAME = "key_points.json"
_DAEMON_STATE_FILENAME = "daemon_state.json"


def _load_key_points(session_folder: Path) -> list[dict]:
    """Load key points from session folder. Supports old locked/draft format for migration."""
    cache_file = session_folder / _KEY_POINTS_FILENAME
    if not cache_file.exists():
        return []
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        # Support new format {"points": [...]} and old format {"locked": [...], "draft": [...]}
        points = data.get("points", data.get("locked", []) + data.get("draft", []))
        print(f"[session] Loaded {len(points)} key points from {session_folder.name}")
        return points
    except Exception as e:
        print(f"[session] Failed to load key points: {e}", file=sys.stderr)
        return []


def _save_key_points(session_folder: Path, points: list[dict]) -> None:
    """Save key points to session folder."""
    try:
        session_folder.mkdir(parents=True, exist_ok=True)
        (session_folder / _KEY_POINTS_FILENAME).write_text(
            json.dumps({"points": points}, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[session] Failed to save key points: {e}", file=sys.stderr)


def _load_daemon_state(sessions_root: Path) -> list[dict]:
    """Load session stack from daemon state file."""
    state_file = sessions_root / _DAEMON_STATE_FILENAME
    if not state_file.exists():
        return []
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return data.get("stack", [])
    except Exception as e:
        print(f"[session] Failed to load daemon state: {e}", file=sys.stderr)
        return []


def _save_daemon_state(sessions_root: Path, stack: list[dict]) -> None:
    """Persist session stack to daemon state file."""
    try:
        sessions_root.mkdir(parents=True, exist_ok=True)
        (sessions_root / _DAEMON_STATE_FILENAME).write_text(
            json.dumps({"stack": stack}, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[session] Failed to save daemon state: {e}", file=sys.stderr)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_daemon.py::TestSessionKeyPoints -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add training_daemon.py tests/test_daemon.py
git commit -m "feat: session key points & daemon state persistence"
```

---

### Task 5: Daemon — Session Request Polling & Stack Operations

**Files:**
- Modify: `training_daemon.py` (main loop — add session request polling, stack push/pop/rename, replace locked/draft initialization)

- [ ] **Step 1: Add helper functions**

```python
def _find_notes_in_folder(folder: Path) -> Path | None:
    """Find the most recently modified .txt notes file in a session folder."""
    if not folder.exists():
        return None
    txt_files = sorted(
        [f for f in folder.iterdir() if f.suffix.lower() == ".txt"],
        key=lambda f: f.stat().st_mtime,
    )
    return txt_files[-1] if txt_files else None


def _sync_session_to_server(config, stack: list[dict], key_points: list[dict]) -> None:
    """Push session stack and key points to server."""
    _post_json(
        f"{config.server_url}/api/session/sync",
        {"stack": stack, "key_points": key_points},
        config.host_username, config.host_password,
    )
```

- [ ] **Step 2: Replace daemon initialization (locked/draft → session stack)**

Replace the existing `locked_points`/`draft_points` initialization block (around lines 307-327) with:

```python
    # ── Session stack initialization ──
    sessions_root = config.session_folder.parent if config.session_folder else Path.cwd()
    session_stack = _load_daemon_state(sessions_root)
    current_key_points: list[dict] = []

    if session_stack:
        # Restore from persisted stack
        current_folder = sessions_root / session_stack[-1]["name"]
        current_key_points = _load_key_points(current_folder)
        print(f"[session] Restored stack ({len(session_stack)} sessions), {len(current_key_points)} key points")
    elif config.session_folder:
        # Auto-start from today's detected session folder
        session_stack = [{
            "name": config.session_folder.name,
            "started_at": datetime.now().isoformat(),
            "ended_at": None,
            "summary_watermark": 0,
        }]
        current_key_points = _load_key_points(config.session_folder)
        _save_daemon_state(sessions_root, session_stack)
        print(f"[session] Auto-started: {config.session_folder.name}")

    # Sync initial state to server
    try:
        _sync_session_to_server(config, session_stack, current_key_points)
    except Exception as e:
        print(f"[session] Failed to sync initial state: {e}", file=sys.stderr)
```

- [ ] **Step 3: Add session request polling to daemon main loop**

In the main `while True` loop, add a new section after heartbeat, before the summary check:

```python
            # ── Check for session management requests ──
            try:
                session_req = _get_json(
                    f"{config.server_url}/api/session/request",
                    config.host_username, config.host_password,
                )
                action = session_req.get("action")
                if action == "start":
                    name = session_req["name"]
                    folder = sessions_root / name
                    folder.mkdir(parents=True, exist_ok=True)
                    new_session = {
                        "name": name,
                        "started_at": datetime.now().isoformat(),
                        "ended_at": None,
                        "summary_watermark": 0,
                    }
                    session_stack.append(new_session)
                    current_key_points = _load_key_points(folder)
                    _save_daemon_state(sessions_root, session_stack)
                    notes_file = _find_notes_in_folder(folder)
                    config = dc_replace(config, session_folder=folder, session_notes=notes_file)
                    _sync_session_to_server(config, session_stack, current_key_points)
                    transcript_state.reset()
                    print(f"[session] Started: {name}")

                elif action == "end" and len(session_stack) > 1:
                    ended = session_stack.pop()
                    ended["ended_at"] = datetime.now().isoformat()
                    ended_folder = sessions_root / ended["name"]
                    _save_key_points(ended_folder, current_key_points)
                    # Restore parent session
                    parent = session_stack[-1]
                    parent_folder = sessions_root / parent["name"]
                    current_key_points = _load_key_points(parent_folder)
                    _save_daemon_state(sessions_root, session_stack)
                    notes_file = _find_notes_in_folder(parent_folder)
                    config = dc_replace(config, session_folder=parent_folder, session_notes=notes_file)
                    _sync_session_to_server(config, session_stack, current_key_points)
                    transcript_state.reset()
                    print(f"[session] Ended: {ended['name']}, restored: {parent['name']}")

                elif action == "rename":
                    new_name = session_req["name"]
                    if session_stack:
                        old_name = session_stack[-1]["name"]
                        new_folder = sessions_root / new_name
                        # Load existing points from new folder FIRST (before overwriting)
                        existing = _load_key_points(new_folder) if new_folder.exists() else []
                        new_folder.mkdir(parents=True, exist_ok=True)
                        if existing:
                            # Folder already had key points — use them
                            current_key_points = existing
                        else:
                            # New/empty folder — carry current points over
                            _save_key_points(new_folder, current_key_points)
                        session_stack[-1]["name"] = new_name
                        _save_daemon_state(sessions_root, session_stack)
                        notes_file = _find_notes_in_folder(new_folder)
                        config = dc_replace(config, session_folder=new_folder, session_notes=notes_file)
                        _sync_session_to_server(config, session_stack, current_key_points)
                        print(f"[session] Renamed: {old_name} → {new_name}")
            except Exception as e:
                print(f"[session] Request error: {e}", file=sys.stderr)
```

- [ ] **Step 4: Update summary generation to use session-aware key points**

Replace the force summary handling block. Key changes:
- Use `current_key_points` instead of `locked_points`/`draft_points`
- Pass last 5 points to `generate_summary()` as context
- Apply the `{updated, new}` response: patch existing points by index, append new ones
- Save to `key_points.json` in current session folder
- Update `summary_watermark` in the session stack entry
- Sync to server after update

```python
            if force_summary and session_stack:
                current_session = session_stack[-1]
                session_folder = sessions_root / current_session["name"]
                watermark = current_session.get("summary_watermark", 0)
                print(f"[summarizer] Generating summary (on-demand, watermark={watermark})")
                last_summary_at = now_mono
                try:
                    entries = load_transcription_files(config.folder)
                    if entries:
                        # TODO Task 7: use extract_text_for_time_window with session time windows
                        full_text = extract_all_text(entries)
                        if full_text:
                            # Use watermark to compute delta
                            delta_text = full_text[watermark:] if watermark < len(full_text) else None
                            if not delta_text:
                                print("[summarizer] No new transcript content — skipping")
                                continue
                            print(f"[summarizer] Delta: {len(delta_text)} chars (full: {len(full_text)} chars)")

                            last_5 = current_key_points[-5:] if current_key_points else []
                            result = generate_summary(config, last_5, delta_text=delta_text)
                            if result is not None:
                                # Apply updates
                                for upd in result.get("updated", []):
                                    idx = upd.get("index")
                                    if idx is not None and 0 <= idx < len(current_key_points):
                                        current_key_points[idx] = {
                                            "text": upd["text"],
                                            "source": upd.get("source", "discussion"),
                                            "time": upd.get("time"),
                                        }
                                # Append new points
                                for new_pt in result.get("new", []):
                                    current_key_points.append({
                                        "text": new_pt["text"],
                                        "source": new_pt.get("source", "discussion"),
                                        "time": new_pt.get("time"),
                                    })

                                # Update watermark
                                current_session["summary_watermark"] = len(full_text)

                                # Persist and sync
                                _save_key_points(session_folder, current_key_points)
                                _save_daemon_state(sessions_root, session_stack)
                                _sync_session_to_server(config, session_stack, current_key_points)
                                print(f"[summarizer] {len(current_key_points)} total key points")
                except Exception as e:
                    print(f"[summarizer] Error: {e}", file=sys.stderr)
```

- [ ] **Step 5: Test manually**

Start the daemon and verify:
- Auto-detection logs the session name
- Brain icon click generates summary into `key_points.json` in the session folder
- Start/End session via host UI works (check daemon logs)

- [ ] **Step 6: Commit**

```bash
git add training_daemon.py
git commit -m "feat: daemon session stack management with polling and summary generation"
```

---

### Task 6: Summarizer — Updated/New Response Format

**Files:**
- Modify: `daemon/summarizer.py` (new prompt + response parsing)
- Test: `tests/test_daemon.py`

- [ ] **Step 1: Write failing test for new response format**

```python
class TestSummarizerUpdatedFormat:
    def _cfg(self, tmp_path):
        from quiz_core import Config
        return Config(
            folder=tmp_path, minutes=30, server_url="http://localhost",
            api_key="key", model="model", dry_run=False,
            host_username="h", host_password="p",
        )

    @patch("daemon.summarizer.read_session_notes", return_value="")
    @patch("daemon.summarizer.create_message")
    def test_updated_and_new_format(self, mock_create, *_mocks):
        resp_text = json.dumps({
            "updated": [{"index": 0, "text": "Revised point", "source": "discussion", "time": "14:30"}],
            "new": [{"text": "Brand new point", "source": "discussion", "time": "15:10"}],
        })
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(type="text", text=resp_text)]
        mock_resp.stop_reason = "end_turn"
        mock_create.return_value = mock_resp

        existing = [{"text": "Old point", "source": "discussion", "time": "10:00"}]
        result = generate_summary(self._cfg(MagicMock()), existing, delta_text="new transcript")
        assert result is not None
        assert len(result["updated"]) == 1
        assert result["updated"][0]["index"] == 0
        assert len(result["new"]) == 1

    @patch("daemon.summarizer.read_session_notes", return_value="")
    @patch("daemon.summarizer.create_message")
    def test_new_only_no_updates(self, mock_create, *_mocks):
        resp_text = json.dumps({
            "updated": [],
            "new": [{"text": "Fresh point", "source": "notes"}],
        })
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(type="text", text=resp_text)]
        mock_resp.stop_reason = "end_turn"
        mock_create.return_value = mock_resp

        result = generate_summary(self._cfg(MagicMock()), [], delta_text="some text")
        assert result is not None
        assert len(result["updated"]) == 0
        assert len(result["new"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_daemon.py::TestSummarizerUpdatedFormat -v`
Expected: FAIL

- [ ] **Step 3: Update summarizer prompt and response parsing**

In `daemon/summarizer.py`:

1. Update `_SUMMARY_SYSTEM_PROMPT` — replace the output rules section to instruct the LLM to return `{"updated": [...], "new": [...]}` format. Include in the prompt that it receives recent key points with indices that it may update.

2. Update `generate_summary()` signature: change `locked_points` parameter to `existing_points` (last 5 points for context).

3. In the user message builder, replace the "ESTABLISHED KEY POINTS" section with:
```python
if existing_points:
    indexed_texts = "\n".join(f"  [{i}] {p['text']}" for i, p in enumerate(existing_points))
    parts.append(f"RECENT KEY POINTS (you may update by index, or add new):\n{indexed_texts}\n")
```

4. Update response parsing to expect `{"updated": [...], "new": [...]}` format instead of a flat array. Return this dict directly (or `None` on failure).

5. Keep backward compatibility: if the response is a flat array (legacy), wrap it as `{"updated": [], "new": parsed}`.

- [ ] **Step 4: Update existing tests for new signature**

The existing `TestGenerateSummary` tests pass `locked_points=[]` as the second arg. Update them to pass `existing_points=[]` (or whatever the new param name is). Update their assertions to match the new `{"updated": [...], "new": [...]}` return type.

- [ ] **Step 5: Run all summarizer tests**

Run: `python3 -m pytest tests/test_daemon.py::TestSummarizerUpdatedFormat tests/test_daemon.py::TestGenerateSummary -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add daemon/summarizer.py tests/test_daemon.py
git commit -m "feat: summarizer returns updated/new format with point patching"
```

---

### Task 7: Transcript Time-Windowing

**Files:**
- Modify: `quiz_core.py` (add `extract_text_for_time_window` function)
- Modify: `training_daemon.py` (wire time-windowing into summary generation)
- Test: `tests/test_quiz_core.py`

- [ ] **Step 1: Write failing test for time-window filtering**

In `tests/test_quiz_core.py`, add:

```python
from quiz_core import extract_text_for_time_window


class TestTimeWindowExtraction:
    def test_basic_window(self):
        entries = [
            (3600 * 9, "morning talk"),       # 09:00
            (3600 * 12, "lunch topic"),        # 12:00
            (3600 * 13, "afternoon talk"),     # 13:00
        ]
        text = extract_text_for_time_window(
            entries,
            start_ts=3600 * 9,
            end_ts=3600 * 17,
            exclude_ranges=[(3600 * 12, 3600 * 13)],
        )
        assert "morning talk" in text
        assert "afternoon talk" in text
        assert "lunch topic" not in text

    def test_no_exclusions(self):
        entries = [(3600 * 10, "hello"), (3600 * 11, "world")]
        text = extract_text_for_time_window(entries, start_ts=3600 * 9, end_ts=3600 * 12)
        assert "hello" in text
        assert "world" in text

    def test_empty_when_all_excluded(self):
        entries = [(3600 * 12, "lunch only")]
        text = extract_text_for_time_window(
            entries, start_ts=3600 * 9, end_ts=3600 * 17,
            exclude_ranges=[(3600 * 11, 3600 * 13)],
        )
        assert text == ""

    def test_none_timestamps_skipped(self):
        entries = [(None, "no ts"), (3600 * 10, "has ts")]
        text = extract_text_for_time_window(entries, start_ts=3600 * 9)
        assert "has ts" in text
        assert "no ts" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_quiz_core.py::TestTimeWindowExtraction -v`
Expected: FAIL

- [ ] **Step 3: Implement extract_text_for_time_window**

In `quiz_core.py`, add after `extract_all_text`:

```python
def extract_text_for_time_window(
    entries: list,
    start_ts: float,
    end_ts: float | None = None,
    exclude_ranges: list[tuple[float, float]] | None = None,
) -> str:
    """Extract transcript text within a time window, excluding nested session ranges.
    Timestamps are seconds-from-midnight. HH:MM markers added at ~1 min intervals."""
    exclude_ranges = exclude_ranges or []

    def _in_excluded(ts: float) -> bool:
        return any(lo <= ts < hi for lo, hi in exclude_ranges)

    selected = []
    for ts, txt in entries:
        if ts is None:
            continue
        if ts < start_ts:
            continue
        if end_ts is not None and ts >= end_ts:
            continue
        if _in_excluded(ts):
            continue
        selected.append((ts, txt))

    if not selected:
        return ""

    parts: list[str] = []
    last_marker_ts: float = -120.0
    for ts, txt in selected:
        if ts - last_marker_ts >= 60:
            h, remainder = divmod(int(ts), 3600)
            m, _ = divmod(remainder, 60)
            parts.append(f"\n[{h:02d}:{m:02d}]")
            last_marker_ts = ts
        parts.append(txt)

    text = " ".join(parts)
    if len(text) > MAX_CHARS_TO_CLAUDE:
        text = text[-MAX_CHARS_TO_CLAUDE:]
    return text.strip()
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_quiz_core.py::TestTimeWindowExtraction -v`
Expected: All PASS

- [ ] **Step 5: Wire into daemon summary generation**

In `training_daemon.py`, update the summary generation block in Task 5 Step 4. Replace the simple `extract_all_text` call with `extract_text_for_time_window`, using:
- `start_ts`: parse current session's `started_at` to seconds-from-midnight
- `exclude_ranges`: collect `[started_at, ended_at]` of any ended sessions that were nested within the current session (from daemon_state history)

For now, a simple approach: convert session `started_at` ISO string to seconds-from-midnight using `datetime.fromisoformat()`, then pass to `extract_text_for_time_window`.

- [ ] **Step 6: Commit**

```bash
git add quiz_core.py tests/test_quiz_core.py training_daemon.py
git commit -m "feat: transcript time-windowing with nested session exclusion"
```

---

### Task 8: Integration Testing & Cleanup

**Files:**
- Modify: `tests/test_main.py` (integration test for full session lifecycle)
- Modify: `training_daemon.py` (remove old summary_cache references)
- Modify: `state.py` (remove `summary_force_full_day`)
- Modify: `routers/summary.py` (remove `full_day` handling)

- [ ] **Step 1: Write integration test**

```python
def test_session_lifecycle_via_endpoints():
    state.reset()
    client = TestClient(app)

    # Start session
    client.post("/api/session/start", json={"name": "Workshop"}, headers=_HOST_AUTH_HEADERS)
    req = client.get("/api/session/request", headers=_HOST_AUTH_HEADERS).json()
    assert req["action"] == "start"
    assert req["name"] == "Workshop"

    # Simulate daemon sync
    resp = client.post("/api/session/sync", json={
        "stack": [{"name": "Workshop", "started_at": "2026-03-23T09:00:00", "ended_at": None}],
        "key_points": [{"text": "Point 1", "source": "discussion"}],
    }, headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200

    # Verify summary points updated via sync
    summary = client.get("/api/summary").json()
    assert len(summary["points"]) == 1
    assert state.session_stack[0]["name"] == "Workshop"

    # Start nested session
    client.post("/api/session/start", json={"name": "Lunch Talk"}, headers=_HOST_AUTH_HEADERS)
    req2 = client.get("/api/session/request", headers=_HOST_AUTH_HEADERS).json()
    assert req2["action"] == "start"

    # End session
    client.post("/api/session/end", headers=_HOST_AUTH_HEADERS)
    req3 = client.get("/api/session/request", headers=_HOST_AUTH_HEADERS).json()
    assert req3["action"] == "end"

    # Rename
    client.patch("/api/session/rename", json={"name": "New Name"}, headers=_HOST_AUTH_HEADERS)
    req4 = client.get("/api/session/request", headers=_HOST_AUTH_HEADERS).json()
    assert req4["action"] == "rename"
    assert req4["name"] == "New Name"
```

- [ ] **Step 2: Run all tests**

Run: `python3 -m pytest tests/test_main.py tests/test_daemon.py tests/test_quiz_core.py -v --tb=short`
Expected: All PASS

- [ ] **Step 3: Remove deprecated code**

- In `state.py`: remove `self.summary_force_full_day: bool = False`
- In `routers/summary.py`: remove `ForceRequest` model, revert `POST /api/summary/force` to not accept `full_day` body; remove `full_day` from `GET /api/summary/force` response
- In `training_daemon.py`: remove old `_load_summary_cache`/`_save_summary_cache` if still present; remove `_SUMMARY_CACHE_FILENAME = "summary_cache.json"` constant; remove all references to `locked_points`/`draft_points` variables

- [ ] **Step 4: Run full test suite**

Run: `python3 -m pytest tests/ -v --ignore=tests/test_e2e*.py --ignore=tests/test_load.py --tb=short`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add state.py routers/summary.py training_daemon.py tests/test_main.py
git commit -m "feat: session stack complete — cleanup old summary model"
```

- [ ] **Step 6: Push to master**

```bash
git fetch origin master && git rebase origin/master && git push origin HEAD:master
```
