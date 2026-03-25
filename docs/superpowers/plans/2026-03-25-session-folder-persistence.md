# Session Folder Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist participant names, scores, and activity state to per-session JSON files on disk so the live workshop session survives server restarts, and isolate workshop vs. talk participants when sessions are nested.

**Architecture:** The training daemon (running on trainer's Mac) periodically snapshots the server's AppState to `session_state.json` in the active session folder by calling a new `GET /api/session/snapshot` endpoint every 5s. On server restart the daemon detects the gap and immediately posts the snapshot back via the extended `POST /api/session/sync`. WebSocket connections are resolved against the active session's known UUIDs so participants from a paused session receive a "Session paused" overlay and auto-reconnect when their session is restored.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, plain vanilla JS, pytest, `pathlib.Path` for file I/O, `datetime` for timing logic.

---

## File Map

| File | Change |
|---|---|
| `state.py` | Replace `session_stack` with `session_main` + `session_talk` + `paused_participant_uuids` |
| `routers/session.py` | New `/api/session/snapshot`; extend `/api/session/sync`; replace start/end with start_talk/end_talk |
| `routers/ws.py` | UUID resolution (3 branches) + send `session_paused` message |
| `messaging.py` | Serialize `session_main`/`session_talk` instead of `session_stack` |
| `training_daemon.py` | daemon_state.json `{main,talk}` schema; periodic 5s save; START TALK/END TALK; 5:30/6pm/midnight timing |
| `daemon/summarizer.py` | Rename `transcript_keypoints.md` → `transcript_discussion.md` (load/save) |
| `static/host.html` | Sessions panel redesign: START TALK, END TALK, FRAGILE CREATE, remove rename |
| `static/host.js` | `renderSessionPanel()` rewrite, new action handlers |
| `static/participant.html` | Add `session-paused-overlay` div |
| `static/participant.js` | Handle `session_paused` message type |

---

## Task 1: Rename transcript_keypoints.md → transcript_discussion.md

**Files:**
- Modify: `training_daemon.py` (all `transcript_keypoints` string literals)
- Modify: `daemon/summarizer.py` (same)

- [ ] **Step 1: Write the failing test**

In `tests/test_main.py` or `tests/test_daemon_discussion.py`:

```python
import tempfile
from pathlib import Path

def test_load_discussion_new_filename():
    """_load_key_points reads transcript_discussion.md when present."""
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        discussion = folder / "transcript_discussion.md"
        discussion.write_text("---\nwatermark: 5\n---\n\nMon 10:00 Test point\n")
        from training_daemon import _load_key_points
        points, watermark = _load_key_points(folder)
        assert watermark == 5
        assert len(points) == 1
        assert "Test point" in points[0]["text"]

def test_load_discussion_falls_back_to_old_filename():
    """_load_key_points falls back to transcript_keypoints.md for legacy folders."""
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        old = folder / "transcript_keypoints.md"
        old.write_text("---\nwatermark: 3\n---\n\nMon 09:00 Legacy point\n")
        from training_daemon import _load_key_points
        points, watermark = _load_key_points(folder)
        assert watermark == 3

def test_save_discussion_writes_new_filename():
    """_save_key_points writes transcript_discussion.md, not the old filename."""
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        from training_daemon import _save_key_points
        import datetime
        _save_key_points(folder, [{"text": "Point A", "source": "discussion", "time": "10:00"}], 7, datetime.date.today())
        assert (folder / "transcript_discussion.md").exists()
        assert not (folder / "transcript_keypoints.md").exists()
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/victorrentea/conductor/workspaces/training-assistant/mogadishu-v3
python -m pytest tests/test_daemon_discussion.py -v 2>&1 | head -30
```
Expected: FAIL (old filename used in save)

- [ ] **Step 3: Rename in training_daemon.py**

Replace all occurrences of `"transcript_keypoints.md"` with `"transcript_discussion.md"` in `training_daemon.py`. In `_load_key_points`, keep a fallback that reads the old name if the new one doesn't exist:

```python
DISCUSSION_FILE = "transcript_discussion.md"
DISCUSSION_FILE_LEGACY = "transcript_keypoints.md"

def _load_key_points(session_folder: Path) -> tuple[list, int]:
    md_path = session_folder / DISCUSSION_FILE
    if not md_path.exists():
        md_path = session_folder / DISCUSSION_FILE_LEGACY  # legacy fallback
    if not md_path.exists():
        json_path = session_folder / "key_points.json"
        if json_path.exists():
            # existing legacy JSON fallback (unchanged)
            ...
    ...
```

- [ ] **Step 4: Rename in daemon/summarizer.py**

Replace `"transcript_keypoints.md"` with `"transcript_discussion.md"` in every occurrence.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_daemon_discussion.py -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add training_daemon.py daemon/summarizer.py tests/test_daemon_discussion.py
git commit -m "feat: rename transcript_keypoints.md to transcript_discussion.md"
```

---

## Task 2: Update AppState model — {main, talk} + paused_participant_uuids

**Files:**
- Modify: `state.py`
- Modify: `messaging.py` (serialization)
- Modify: `routers/session.py` (references to session_stack)

**Test isolation note:** The existing `tests/test_main.py` uses a class-based structure with an `autouse=True` reset fixture scoped to that class. New freestanding tests that mutate `state` directly must be placed inside that same class (or a new class with the same autouse fixture) to avoid leaving dirty state for subsequent tests.

- [ ] **Step 1: Write the failing test**

```python
def test_appstate_has_main_talk_fields():
    from state import AppState
    s = AppState()
    assert hasattr(s, 'session_main')
    assert hasattr(s, 'session_talk')
    assert hasattr(s, 'paused_participant_uuids')
    assert s.session_main is None
    assert s.session_talk is None
    assert s.paused_participant_uuids == set()
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_main.py::test_appstate_has_main_talk_fields -v
```

- [ ] **Step 3: Update state.py**

In `AppState.__init__`, replace:
```python
self.session_stack: list[dict] = []
```
with:
```python
self.session_main: dict | None = None   # {name, started_at, status}
self.session_talk: dict | None = None   # {name, started_at, status} | None
self.paused_participant_uuids: set[str] = set()  # UUIDs from the paused session
```

- [ ] **Step 4: Update messaging.py serialization**

In `serialize_state()` (or equivalent broadcast function), replace:
```python
"session_stack": state.session_stack,
```
with:
```python
"session_main": state.session_main,
"session_talk": state.session_talk,
```

- [ ] **Step 5: Update routers/session.py references**

Replace all `state.session_stack` reads/writes with the appropriate `state.session_main` / `state.session_talk` access. The existing `/api/session/sync` handler currently does:
```python
state.session_stack = body.stack
```
Change to:
```python
if body.main is not None or body.talk is not None:
    state.session_main = body.main
    state.session_talk = body.talk
```
Update the Pydantic model for the sync body accordingly.

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/test_main.py -v -k "session"
```
Expected: PASS (or failing only for tests that depend on later tasks)

- [ ] **Step 7: Commit**

```bash
git add state.py messaging.py routers/session.py
git commit -m "feat: replace session_stack with session_main/session_talk in AppState"
```

---

## Task 3: Add GET /api/session/snapshot endpoint

This is the endpoint the daemon calls every 5s to get the full serializable state.

**Files:**
- Modify: `routers/session.py`

- [ ] **Step 1: Write the failing test**

```python
def test_session_snapshot_returns_participants_and_scores(client, auth_headers):
    """GET /api/session/snapshot returns mode, participants, and activity state."""
    from state import state
    state.participant_names["uuid-1"] = "Alice"
    state.scores["uuid-1"] = 100
    state.mode = "workshop"

    resp = client.get("/api/session/snapshot", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "workshop"
    assert "uuid-1" in data["participants"]
    assert data["participants"]["uuid-1"]["name"] == "Alice"
    assert data["participants"]["uuid-1"]["score"] == 100
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_main.py::test_session_snapshot_returns_participants_and_scores -v
```

- [ ] **Step 3: Implement /api/session/snapshot**

Add to `routers/session.py`:

```python
@router.get("/api/session/snapshot")
async def get_session_snapshot(credentials: HTTPBasicCredentials = Depends(verify_credentials)):
    """Returns full serializable session state for daemon to persist to disk."""
    import json
    from datetime import datetime

    def _serialize_set(obj):
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Not serializable: {type(obj)}")

    participants = {}
    for uuid, name in state.participant_names.items():
        participants[uuid] = {
            "name": name,
            "score": state.scores.get(uuid, 0),
            "base_score": state.base_scores.get(uuid, 0),
            "location": state.locations.get(uuid, ""),
            "avatar": state.participant_avatars.get(uuid, ""),
            "universe": state.participant_universes.get(uuid, ""),
        }

    poll_data = None
    if state.poll:
        poll_data = {
            **state.poll,
            "active": state.poll_active,
            "votes": state.votes,
            "vote_times": {uuid: t.isoformat() for uuid, t in state.vote_times.items()},
            "correct_ids": state.poll_correct_ids or [],
            "opened_at": state.poll_opened_at.isoformat() if state.poll_opened_at else None,
            "timer_seconds": state.poll_timer_seconds,
            "timer_started_at": state.poll_timer_started_at.isoformat() if state.poll_timer_started_at else None,
        }

    qa_questions = []
    for q in state.qa_questions.values():
        qa_questions.append({**q, "upvoters": list(q.get("upvoters", set()))})

    debate_data = {
        "statement": state.debate_statement,
        "phase": state.debate_phase,
        "sides": state.debate_sides,
        "arguments": [
            {**a, "upvoters": list(a.get("upvoters", set()))}
            for a in state.debate_arguments
        ],
        "champions": state.debate_champions,
        "auto_assigned": list(state.debate_auto_assigned),
        "first_side": state.debate_first_side,
        "round_index": state.debate_round_index,
        "round_timer_seconds": state.debate_round_timer_seconds,
        "round_timer_started_at": state.debate_round_timer_started_at.isoformat() if state.debate_round_timer_started_at else None,
    }

    codereview_data = {
        "snippet": state.codereview_snippet,
        "language": state.codereview_language,
        "phase": state.codereview_phase,
        "confirmed": list(state.codereview_confirmed),
        "selections": {uuid: list(lines) for uuid, lines in state.codereview_selections.items()},
    }

    return {
        "saved_at": datetime.utcnow().isoformat(),
        "mode": state.mode,
        "participants": participants,
        "activity": state.current_activity.value if state.current_activity else "none",
        "poll": poll_data,
        "qa": {"questions": qa_questions},
        "wordcloud": {
            "topic": state.wordcloud_topic,
            "words": state.wordcloud_words,
            "word_order": getattr(state, 'wordcloud_word_order', []),
        },
        "debate": debate_data,
        "codereview": codereview_data,
        "leaderboard_active": state.leaderboard_active,
        "token_usage": state.token_usage,
    }
```

- [ ] **Step 4: Run test**

```bash
python -m pytest tests/test_main.py::test_session_snapshot_returns_participants_and_scores -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add routers/session.py tests/test_main.py
git commit -m "feat: add GET /api/session/snapshot for daemon persistence"
```

---

## Task 4: Extend POST /api/session/sync to restore session_state

When the daemon reconnects after a server restart, it posts the saved snapshot back.

**Files:**
- Modify: `routers/session.py`
- Modify: `state.py` (add restore helper)

- [ ] **Step 1: Write the failing test**

```python
def test_session_sync_restores_participants_and_scores(client, auth_headers):
    """POST /api/session/sync with session_state restores participants and scores."""
    from state import state

    payload = {
        "main": {"name": "2026-03-25 Test", "started_at": "2026-03-25T09:00:00", "status": "active"},
        "talk": None,
        "discussion_points": [],
        "session_state": {
            "saved_at": "2026-03-25T10:00:00",
            "mode": "workshop",
            "participants": {
                "uuid-restored": {"name": "Bob", "score": 250, "base_score": 200, "location": "Cluj", "avatar": "", "universe": ""}
            },
            "activity": "none",
            "poll": None,
            "qa": {"questions": []},
            "wordcloud": {"topic": "", "words": {}},
            "debate": {"statement": None, "phase": None, "sides": {}, "arguments": [], "champions": {}, "auto_assigned": [], "first_side": None, "round_index": None, "round_timer_seconds": None, "round_timer_started_at": None},
            "codereview": {"snippet": None, "language": None, "phase": "idle", "confirmed": [], "selections": {}},
            "leaderboard_active": False,
            "token_usage": {"input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0},
        }
    }
    resp = client.post("/api/session/sync", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    assert state.participant_names.get("uuid-restored") == "Bob"
    assert state.scores.get("uuid-restored") == 250
    assert state.mode == "workshop"
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_main.py::test_session_sync_restores_participants_and_scores -v
```

- [ ] **Step 3: Update /api/session/sync Pydantic model**

In `routers/session.py`, update the `SyncBody` Pydantic model:

```python
class SyncBody(BaseModel):
    main: dict | None = None
    talk: dict | None = None
    discussion_points: list = []
    session_state: dict | None = None  # full snapshot for restore
    action: str | None = None          # "start_talk" | "end_talk" — drives paused_participant_uuids update
    # backward compat:
    stack: list | None = None
    key_points: list | None = None
```

- [ ] **Step 4: Implement restore logic in the sync handler**

In `routers/session.py`, after updating `state.session_main`/`session_talk`, add:

```python
# Manage paused participants BEFORE restoring (so new state doesn't overwrite them)
if body.action == "start_talk":
    state.paused_participant_uuids = set(state.participant_names.keys())
elif body.action == "end_talk":
    state.paused_participant_uuids = set(state.participant_names.keys())

if body.session_state:
    _restore_state_from_snapshot(body.session_state)

# After restore: if no action, clear paused set (plain server-restart restore)
if body.action is None and body.session_state:
    state.paused_participant_uuids = set()
```

Add the restore function (can be in `routers/session.py` or a new `state_restore.py`):

```python
def _restore_state_from_snapshot(snap: dict):
    from datetime import datetime
    # Participants
    state.participant_names.clear()
    state.scores.clear()
    state.base_scores.clear()
    state.locations.clear()
    state.participant_avatars.clear()
    state.participant_universes.clear()
    for uuid, p in (snap.get("participants") or {}).items():
        state.participant_names[uuid] = p["name"]
        state.scores[uuid] = p.get("score", 0)
        state.base_scores[uuid] = p.get("base_score", 0)
        state.locations[uuid] = p.get("location", "")
        state.participant_avatars[uuid] = p.get("avatar", "")
        state.participant_universes[uuid] = p.get("universe", "")
    # Mode
    if snap.get("mode"):
        state.mode = snap["mode"]
    # Activity
    if snap.get("activity"):
        from state import ActivityType
        try:
            state.current_activity = ActivityType(snap["activity"])
        except ValueError:
            pass
    # Poll
    if snap.get("poll"):
        p = snap["poll"]
        exclude = {"active", "votes", "vote_times", "correct_ids", "opened_at", "timer_seconds", "timer_started_at"}
        state.poll = {k: v for k, v in p.items() if k not in exclude}
        state.poll_active = p.get("active", False)
        state.votes = p.get("votes") or {}
        state.vote_times = {uuid: datetime.fromisoformat(t) for uuid, t in (p.get("vote_times") or {}).items()}
        state.poll_correct_ids = p.get("correct_ids")
        state.poll_opened_at = datetime.fromisoformat(p["opened_at"]) if p.get("opened_at") else None
        state.poll_timer_seconds = p.get("timer_seconds")
        state.poll_timer_started_at = datetime.fromisoformat(p["timer_started_at"]) if p.get("timer_started_at") else None
    # QA
    qa = snap.get("qa") or {}
    state.qa_questions.clear()
    for q in qa.get("questions") or []:
        q_copy = dict(q)
        q_copy["upvoters"] = set(q_copy.get("upvoters") or [])
        state.qa_questions[q_copy["id"]] = q_copy
    # Wordcloud
    wc = snap.get("wordcloud") or {}
    state.wordcloud_topic = wc.get("topic", "")
    state.wordcloud_words = wc.get("words") or {}
    if hasattr(state, 'wordcloud_word_order'):
        state.wordcloud_word_order = wc.get("word_order") or []
    # Debate
    debate = snap.get("debate") or {}
    state.debate_statement = debate.get("statement")
    state.debate_phase = debate.get("phase")
    state.debate_sides = debate.get("sides") or {}
    state.debate_arguments = [
        {**a, "upvoters": set(a.get("upvoters") or [])} for a in (debate.get("arguments") or [])
    ]
    state.debate_champions = debate.get("champions") or {}
    state.debate_auto_assigned = set(debate.get("auto_assigned") or [])
    state.debate_first_side = debate.get("first_side")
    state.debate_round_index = debate.get("round_index")
    # Codereview
    cr = snap.get("codereview") or {}
    state.codereview_snippet = cr.get("snippet")
    state.codereview_language = cr.get("language")
    state.codereview_phase = cr.get("phase", "idle")
    state.codereview_confirmed = set(cr.get("confirmed") or [])
    state.codereview_selections = {uuid: set(lines) for uuid, lines in (cr.get("selections") or {}).items()}
    # Misc
    state.leaderboard_active = snap.get("leaderboard_active", False)
    if snap.get("token_usage"):
        state.token_usage.update(snap["token_usage"])
```

- [ ] **Step 5: Run test**

```bash
python -m pytest tests/test_main.py::test_session_sync_restores_participants_and_scores -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add routers/session.py tests/test_main.py
git commit -m "feat: extend /api/session/sync to restore full session state on server restart"
```

---

## Task 5: Update daemon_state.json to {main, talk} schema

**Files:**
- Modify: `training_daemon.py` (`_load_daemon_state`, `_save_daemon_state`, all callers)

- [ ] **Step 1: Write the failing test**

```python
import json, tempfile
from pathlib import Path

def test_load_daemon_state_new_format():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "daemon_state.json"
        f.write_text(json.dumps({
            "main": {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00", "status": "active"},
            "talk": None
        }))
        from training_daemon import _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result["main"]["name"] == "2026-03-25 WS"
        assert result["talk"] is None

def test_load_daemon_state_migrates_old_stack_format():
    """Old {stack:[...]} format is migrated to {main, talk}."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "daemon_state.json"
        f.write_text(json.dumps({
            "stack": [
                {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00"}
            ]
        }))
        from training_daemon import _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result["main"]["name"] == "2026-03-25 WS"
        assert result["talk"] is None

def test_save_daemon_state_writes_new_format():
    with tempfile.TemporaryDirectory() as d:
        from training_daemon import _save_daemon_state
        _save_daemon_state(Path(d), {
            "main": {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00", "status": "active"},
            "talk": None
        })
        data = json.loads((Path(d) / "daemon_state.json").read_text())
        assert "main" in data
        assert "stack" not in data
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_daemon_state.py -v 2>&1 | head -20
```

- [ ] **Step 3: Rewrite _load_daemon_state and _save_daemon_state**

```python
def _load_daemon_state(sessions_root: Path) -> dict:
    """Returns {main: dict|None, talk: dict|None}. Migrates old {stack:[]} format."""
    path = sessions_root / "daemon_state.json"
    empty = {"main": None, "talk": None}
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text())
    except Exception:
        return empty
    # Migration: old format had {stack: [...]}
    if "stack" in data and "main" not in data:
        stack = data["stack"]
        active = [s for s in stack if not s.get("ended_at")]
        data = {
            "main": {**active[0], "status": "active"} if len(active) >= 1 else None,
            "talk": {**active[1], "status": "active"} if len(active) >= 2 else None,
        }
    return data

def _save_daemon_state(sessions_root: Path, state: dict):
    """Writes {main, talk} to daemon_state.json atomically."""
    path = sessions_root / "daemon_state.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, default=str, indent=2))
    tmp.replace(path)
```

- [ ] **Step 4: Update all callers** in `training_daemon.py`

Replace all references from `_load_daemon_state(sessions_root)["stack"]` to the new `{main, talk}` structure. Key changes:
- Startup: `daemon_state["main"]` gives current main session; `daemon_state["talk"]` gives talk (if any)
- After START TALK: set `daemon_state["talk"] = {name, started_at, status: "active"}`, save
- After END TALK: set `daemon_state["talk"] = None`, save
- After PAUSE: update `daemon_state["main"]["status"] = "paused"`, save
- After RESUME: update `daemon_state["main"]["status"] = "active"`, save
- Midnight: update `daemon_state["main"]["status"] = "ended"`, save

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_daemon_state.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add training_daemon.py tests/test_daemon_state.py
git commit -m "feat: update daemon_state.json to {main, talk} schema with migration from old stack format"
```

---

## Task 6: Daemon periodic session_state.json save (every 5s)

**Files:**
- Modify: `training_daemon.py`

- [ ] **Step 1: Write the test**

```python
import json, tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

def test_save_session_state_writes_json():
    """_save_session_state writes session_state.json to the session folder."""
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        snapshot = {
            "saved_at": "2026-03-25T10:00:00",
            "mode": "workshop",
            "participants": {"uuid-1": {"name": "Alice", "score": 100}},
        }
        from training_daemon import _save_session_state
        _save_session_state(folder, snapshot)
        written = json.loads((folder / "session_state.json").read_text())
        assert written["participants"]["uuid-1"]["name"] == "Alice"
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_daemon_save.py -v 2>&1 | head -20
```

- [ ] **Step 3: Implement _save_session_state and periodic call in daemon loop**

Add to `training_daemon.py`:

```python
def _save_session_state(session_folder: Path, snapshot: dict):
    """Atomically writes session_state.json to the session folder."""
    path = session_folder / "session_state.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot, default=str, indent=2))
    tmp.replace(path)
    _log_debug(f"session_state.json saved ({len(snapshot.get('participants', {}))} participants)")
```

In the daemon's main polling loop, add a save counter. After every ~5 seconds (i.e., after N loop iterations where each iteration is ~1s), if a session folder is active:

```python
_save_counter = 0
_SAVE_INTERVAL = 5  # save every 5 loop iterations (~5s)

# In the main loop:
_save_counter += 1
if _save_counter >= _SAVE_INTERVAL and current_session_folder:
    _save_counter = 0
    try:
        resp = requests.get(f"{SERVER_URL}/api/session/snapshot", auth=_auth(), timeout=5)
        if resp.ok:
            _save_session_state(current_session_folder, resp.json())
    except Exception as e:
        logger.error(f"Failed to save session snapshot: {e}")
```

Also call `_save_session_state` immediately (with first snapshot) when a session folder is first set (START TALK, or session auto-open at startup).

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_daemon_save.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add training_daemon.py tests/test_daemon_save.py
git commit -m "feat: daemon writes session_state.json every 5s via /api/session/snapshot"
```

---

## Task 7: Daemon START TALK / END TALK actions

Replace the old generic start/end session model with explicit `start_talk` / `end_talk` action types.

**Files:**
- Modify: `training_daemon.py` (action handlers in polling loop)
- Modify: `routers/session.py` (new request endpoints)

- [ ] **Step 1: Write the test**

```python
def test_start_talk_action_creates_folder_and_syncs(client, auth_headers, tmp_path, monkeypatch):
    """POST /api/session/start_talk queues a start_talk action."""
    resp = client.post("/api/session/start_talk", headers=auth_headers)
    assert resp.status_code == 200
    from state import state
    assert state.session_request["action"] == "start_talk"

def test_end_talk_action_is_queued(client, auth_headers):
    resp = client.post("/api/session/end_talk", headers=auth_headers)
    assert resp.status_code == 200
    from state import state
    assert state.session_request["action"] == "end_talk"
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_main.py -v -k "start_talk or end_talk"
```

- [ ] **Step 3: Add /api/session/start_talk and /api/session/end_talk endpoints**

In `routers/session.py`:

```python
@router.post("/api/session/start_talk")
async def start_talk(credentials: HTTPBasicCredentials = Depends(verify_credentials)):
    state.session_request = {"action": "start_talk"}
    return {"ok": True}

@router.post("/api/session/end_talk")
async def end_talk(credentials: HTTPBasicCredentials = Depends(verify_credentials)):
    state.session_request = {"action": "end_talk"}
    return {"ok": True}
```

- [ ] **Step 3b: Define _get_current_key_points() helper in training_daemon.py**

This helper returns the in-memory list of current key/discussion points so they can be included in sync payloads. Add near other key-points helpers:

```python
def _get_current_key_points() -> list:
    """Returns the current in-memory key points list (may be empty if not yet loaded)."""
    return current_key_points  # module-level list maintained by the daemon's summary loop
```

`current_key_points` is the module-level variable already maintained by the summarizer. If the variable name differs in the actual code, use whatever name the existing daemon uses for the in-memory points list.

- [ ] **Step 4: Implement START TALK handler in training_daemon.py**

In the daemon's session request handler, add case for `"start_talk"`:

```python
elif action == "start_talk":
    now = datetime.now()
    talk_name = f"{now.strftime('%Y-%m-%d %H:%M')} talk"
    talk_folder = sessions_root / talk_name
    talk_folder.mkdir(exist_ok=True)

    # 1. Save current (main) session state immediately
    if current_session_folder:
        try:
            resp = requests.get(f"{SERVER_URL}/api/session/snapshot", auth=_auth(), timeout=5)
            if resp.ok:
                _save_session_state(current_session_folder, resp.json())
        except Exception as e:
            logger.error(f"START TALK: failed to save main snapshot: {e}")

    # 2. Load talk's existing state (if folder had prior data)
    talk_state = None
    talk_state_path = talk_folder / "session_state.json"
    if talk_state_path.exists():
        try:
            talk_state = json.loads(talk_state_path.read_text())
        except Exception:
            pass

    # 3. Update daemon_state.json
    daemon_state["talk"] = {"name": talk_name, "started_at": now.isoformat(), "status": "active"}
    _save_daemon_state(sessions_root, daemon_state)
    current_session_folder = talk_folder

    # 4. Sync to server (new talk state, disconnect main participants)
    sync_payload = {
        "main": daemon_state["main"],
        "talk": daemon_state["talk"],
        "discussion_points": [],
        "session_state": talk_state,
        "action": "start_talk",  # server uses this to populate paused_participant_uuids
    }
    requests.post(f"{SERVER_URL}/api/session/sync", json=sync_payload, auth=_auth(), timeout=10)
    logger.info(f"START TALK: {talk_name}")
```

- [ ] **Step 5: Implement END TALK handler**

```python
elif action == "end_talk":
    if not daemon_state.get("talk"):
        logger.warning("END TALK requested but no talk is active")
        continue

    # 1. Save talk state
    if current_session_folder:
        try:
            resp = requests.get(f"{SERVER_URL}/api/session/snapshot", auth=_auth(), timeout=5)
            if resp.ok:
                _save_session_state(current_session_folder, resp.json())
        except Exception as e:
            logger.error(f"END TALK: failed to save talk snapshot: {e}")

    # 2. Load main session state for restore
    main_name = daemon_state["main"]["name"] if daemon_state.get("main") else None
    main_folder = sessions_root / main_name if main_name else None
    main_state = None
    if main_folder and (main_folder / "session_state.json").exists():
        try:
            main_state = json.loads((main_folder / "session_state.json").read_text())
        except Exception:
            pass

    # 3. Update daemon_state.json
    daemon_state["talk"] = None
    if daemon_state.get("main"):
        daemon_state["main"]["status"] = "active"
    _save_daemon_state(sessions_root, daemon_state)
    current_session_folder = main_folder

    # 4. Sync to server (restore main, disconnect talk participants)
    sync_payload = {
        "main": daemon_state["main"],
        "talk": None,
        "discussion_points": _get_current_key_points(),  # restore main discussion points
        "session_state": main_state,
        "action": "end_talk",
    }
    requests.post(f"{SERVER_URL}/api/session/sync", json=sync_payload, auth=_auth(), timeout=10)
    logger.info(f"END TALK: restored main session {main_name}")
```

- [ ] **Step 6: Update server-side sync to handle start_talk/end_talk actions**

In `routers/session.py` sync handler, when `body.action == "start_talk"`:
```python
# Save current participants as paused, then clear for talk session
state.paused_participant_uuids = set(state.participant_names.keys())
state.participant_names.clear()
state.scores.clear()
# (other activity state cleared by _restore_state_from_snapshot with empty talk_state)
```

When `body.action == "end_talk"`:
```python
# Clear talk participants as paused, restore main
state.paused_participant_uuids = set(state.participant_names.keys())
# (main state restored by _restore_state_from_snapshot)
```

- [ ] **Step 7: Run tests**

```bash
python -m pytest tests/test_main.py -v -k "talk"
```
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add training_daemon.py routers/session.py tests/test_main.py
git commit -m "feat: implement START TALK / END TALK daemon actions with state save/restore"
```

---

## Task 8: WS UUID resolution + session_paused message

**Files:**
- Modify: `routers/ws.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from fastapi.testclient import TestClient

def test_ws_session_paused_for_other_session_uuid(client):
    """A UUID from the paused session receives session_paused then WS is closed."""
    from state import state
    state.paused_participant_uuids = {"paused-uuid-1"}
    state.participant_names = {}

    with client.websocket_connect("/ws/paused-uuid-1") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "session_paused"
        assert "reconnect" in msg["message"].lower()

def test_ws_unknown_uuid_becomes_new_participant(client):
    """An unknown UUID is accepted and enters set_name flow."""
    from state import state
    state.paused_participant_uuids = set()
    state.participant_names = {}

    with client.websocket_connect("/ws/brand-new-uuid") as ws:
        ws.send_json({"type": "set_name", "name": "Dave"})
        msg = ws.receive_json()
        # Should receive a state update (not session_paused)
        assert msg.get("type") != "session_paused"

def test_ws_known_uuid_is_welcomed_back(client):
    """A UUID already in participant_names is welcomed with their score."""
    from state import state
    state.participant_names["returning-uuid"] = "Carol"
    state.scores["returning-uuid"] = 300
    state.paused_participant_uuids = set()

    with client.websocket_connect("/ws/returning-uuid") as ws:
        ws.send_json({"type": "set_name", "name": "Carol"})
        msg = ws.receive_json()
        assert msg.get("type") != "session_paused"
```

- [ ] **Step 2: Run to verify they fail**

```bash
python -m pytest tests/test_ws_uuid.py -v 2>&1 | head -30
```

- [ ] **Step 3: Add UUID resolution at WS connect in routers/ws.py**

**Critical insertion point:** Place this code AFTER `await websocket.accept()` but BEFORE `state.participants[pid] = websocket`. If the early-return fires after the participant is registered, the UUID stays in `state.participants` forever and future broadcasts will attempt sends to a closed socket.

```python
# UUID resolution: 3 branches
if uuid in state.paused_participant_uuids:
    # Participant belongs to the paused (other) session
    await websocket.send_json({
        "type": "session_paused",
        "message": "Session paused — you'll reconnect automatically"
    })
    await websocket.close()
    return

if uuid not in state.participant_names and uuid not in state.paused_participant_uuids:
    # Unknown UUID: new participant for current session (normal flow, no special handling)
    pass
# else: known UUID in current session → normal flow (welcome back)
```

Note: the existing logic already handles the "known UUID" case (it loads their name/score on first message). The key change is the early-return for paused UUIDs.

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_ws_uuid.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add routers/ws.py tests/test_ws_uuid.py
git commit -m "feat: UUID resolution on WS connect — session_paused for other-session participants"
```

---

## Task 9: Participant session_paused overlay

**Files:**
- Modify: `static/participant.html` (add overlay div)
- Modify: `static/participant.js` (handle `session_paused` message type)

- [ ] **Step 1: Add overlay HTML to participant.html**

Inside `<body>`, add (hidden by default):

```html
<div id="session-paused-overlay" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.85); z-index:9999; align-items:center; justify-content:center; color:#fff; font-size:1.4rem; text-align:center; padding:2rem; flex-direction:column;">
  <div style="margin-bottom:1rem; font-size:2rem;">⏸</div>
  <div id="session-paused-message">Session paused — you'll reconnect automatically</div>
  <div style="margin-top:1rem; font-size:0.9rem; color:#aaa;">Reconnecting…</div>
</div>
```

- [ ] **Step 2: Handle session_paused in participant.js**

In the WebSocket `onmessage` handler, add:

```javascript
if (msg.type === 'session_paused') {
  const overlay = document.getElementById('session-paused-overlay');
  const msgEl = document.getElementById('session-paused-message');
  if (overlay) {
    if (msgEl) msgEl.textContent = msg.message || 'Session paused — you\'ll reconnect automatically';
    overlay.style.display = 'flex';
  }
  return;
}
```

When the WebSocket reconnects successfully (i.e., receives a normal state message with no `session_paused`), hide the overlay:

```javascript
// At the start of normal state processing:
const overlay = document.getElementById('session-paused-overlay');
if (overlay) overlay.style.display = 'none';
```

- [ ] **Step 3: Manual verification**

Start server, manually set `state.paused_participant_uuids = {"test-uuid"}` via a test script, open participant page with `?uuid=test-uuid` (or manipulate localStorage). Verify the overlay appears. Remove the UUID from paused set, reconnect, verify the overlay disappears.

- [ ] **Step 4: Commit**

```bash
git add static/participant.html static/participant.js
git commit -m "feat: show session-paused overlay on participant page when session switches"
```

---

## Task 10: Host UI — sessions panel redesign

Remove the old session stack UI. Implement: main session display + START TALK / END TALK + FRAGILE state with blinking CREATE button.

**Files:**
- Modify: `static/host.html`
- Modify: `static/host.js`

- [ ] **Step 1: Update host.html sessions panel**

Replace the existing `<div class="session-panel">` content with:

```html
<div class="session-panel" id="session-panel">
  <!-- Talk session (shown when session_talk is not null, blinks yellow) -->
  <div id="session-talk-row" style="display:none">
    <div class="session-row session-talk-active" id="session-talk-box">
      <span id="session-talk-name"></span>
      <button class="btn btn-sm btn-danger" onclick="endTalk()">END TALK</button>
    </div>
  </div>

  <!-- Main session row -->
  <div id="session-main-row" style="display:none">
    <div class="session-row">
      <span id="session-main-name"></span>
      <button class="btn btn-sm" id="btn-pause-session" onclick="togglePauseSession()">PAUSE</button>
    </div>
  </div>

  <!-- START TALK button (shown when no talk active) -->
  <div id="session-start-talk-row">
    <button class="btn btn-sm" id="btn-start-talk" onclick="startTalk()">START TALK</button>
  </div>

  <!-- FRAGILE state: CREATE button (shown when no folder for today) -->
  <div id="session-fragile-row" style="display:none">
    <input type="text" id="session-create-input" placeholder="Session name" oninput="updateCreateBtn()">
    <button class="btn btn-sm btn-warning session-fragile-blink" id="btn-create-session"
            onclick="createSession()" disabled>CREATE</button>
  </div>
</div>
```

Add CSS for blinking effects (in host.html `<style>` or host.css):

```css
@keyframes blink-yellow {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
.session-talk-active {
  animation: blink-yellow 1s ease-in-out infinite;
  border: 2px solid #f5a623;
  border-radius: 4px;
  padding: 4px 8px;
}
.session-fragile-blink {
  animation: blink-yellow 0.7s ease-in-out infinite;
}
.session-pause-blinking {
  animation: blink-yellow 1s ease-in-out infinite;
  color: #f5a623;
}
```

- [ ] **Step 2: Rewrite session rendering in host.js**

Replace `renderSessionPanel()` / `renderSessionList()` with:

```javascript
function renderSessionPanel() {
  const main = sessionMain;   // set from WS state: msg.session_main
  const talk = sessionTalk;   // set from WS state: msg.session_talk
  const daemonSeen = daemonLastSeen;  // from msg.daemon_last_seen

  // FRAGILE: daemon connected, no main session
  const fragile = daemonSeen && !main;
  document.getElementById('session-fragile-row').style.display = fragile ? 'flex' : 'none';
  if (fragile) {
    const today = new Date().toISOString().slice(0, 10);
    const input = document.getElementById('session-create-input');
    if (!input.value) input.value = today + ' ';
  }

  // Main session row
  document.getElementById('session-main-row').style.display = main ? 'flex' : 'none';
  if (main) {
    document.getElementById('session-main-name').textContent = main.name;
    const pauseBtn = document.getElementById('btn-pause-session');
    const paused = main.status === 'paused';
    pauseBtn.textContent = paused ? 'RESUME' : 'PAUSE';
    pauseBtn.title = paused ? 'Resume recording' : 'Pause recording';
    pauseBtn.classList.toggle('session-pause-blinking', paused);
  }

  // Talk row
  document.getElementById('session-talk-row').style.display = talk ? 'flex' : 'none';
  if (talk) {
    document.getElementById('session-talk-name').textContent = talk.name;
  }

  // START TALK button: show only when no talk active
  document.getElementById('session-start-talk-row').style.display = (!talk) ? 'flex' : 'none';
}

function startTalk() {
  fetch('/api/session/start_talk', {method: 'POST', headers: authHeaders()})
    .catch(e => console.error('startTalk failed:', e));
}

function endTalk() {
  fetch('/api/session/end_talk', {method: 'POST', headers: authHeaders()})
    .catch(e => console.error('endTalk failed:', e));
}

function createSession() {
  const name = document.getElementById('session-create-input').value.trim();
  if (!name) return;
  fetch('/api/session/create', {
    method: 'POST',
    headers: {...authHeaders(), 'Content-Type': 'application/json'},
    body: JSON.stringify({name})
  }).catch(e => console.error('createSession failed:', e));
}

function updateCreateBtn() {
  const name = document.getElementById('session-create-input').value.trim();
  document.getElementById('btn-create-session').disabled = !name;
}

function togglePauseSession() {
  const paused = sessionMain && sessionMain.status === 'paused';
  const endpoint = paused ? '/api/session/resume' : '/api/session/pause';
  fetch(endpoint, {method: 'POST', headers: authHeaders()})
    .catch(e => console.error('togglePauseSession failed:', e));
}
```

- [ ] **Step 3: Add /api/session/create endpoint**

In `routers/session.py`:

```python
@router.post("/api/session/create")
async def create_session(body: SessionBody, credentials: HTTPBasicCredentials = Depends(verify_credentials)):
    """Host creates a new main session folder (FRAGILE state resolution)."""
    state.session_request = {"action": "create", "name": body.name}
    return {"ok": True}
```

Handle `"create"` in daemon: create the folder, set it as `daemon_state["main"]`, start the 5s save loop.

- [ ] **Step 4: Update WS message handler in host.js**

In the WebSocket `onmessage` handler, handle the new fields:

```javascript
if (msg.session_main !== undefined) sessionMain = msg.session_main;
if (msg.session_talk !== undefined) sessionTalk = msg.session_talk;
// Remove: sessionStack handling
renderSessionPanel();
```

- [ ] **Step 5: Remove rename button**

Search for any `renameSession`, `btn-rename`, or `✏️` references in `host.js` and `host.html` and remove them.

- [ ] **Step 6: Add 5:30pm / 6pm warning banner HTML**

In `host.html`, add a hidden banner:

```html
<div id="recording-warning-banner" style="display:none; background:#f5a623; color:#000; text-align:center; padding:8px; font-weight:bold; animation: blink-yellow 1s ease-in-out infinite;">
  Recording pauses in <span id="recording-warning-countdown">30</span> min
</div>
```

The daemon will push a `recording_warning` WS event (Task 11) that makes this banner visible.

- [ ] **Step 7: Manual verification**

Start server + open `/host`. Verify:
- FRAGILE state shows blinking CREATE button when no session active
- START TALK button creates talk row with blinking border
- END TALK restores main session row
- PAUSE button blinks yellow when paused

- [ ] **Step 8: Commit**

```bash
git add static/host.html static/host.js routers/session.py
git commit -m "feat: redesign host sessions panel with START TALK, END TALK, and FRAGILE CREATE state"
```

---

## Task 11: Daemon 5:30pm / 6pm / midnight timing

**Files:**
- Modify: `training_daemon.py`

- [ ] **Step 1: Write the test**

```python
from datetime import time
from training_daemon import _check_daily_timing

def test_is_in_warning_window():
    assert _check_daily_timing(time(17, 30)) == "warning"
    assert _check_daily_timing(time(17, 59)) == "warning"
    assert _check_daily_timing(time(17, 29)) is None
    assert _check_daily_timing(time(18, 0)) == "auto_pause"
    assert _check_daily_timing(time(20, 0)) == "auto_pause"   # threshold, not window
    assert _check_daily_timing(time(23, 59)) == "midnight"
    assert _check_daily_timing(time(0, 0)) == "midnight"
    assert _check_daily_timing(time(9, 0)) is None

def test_timing_event_endpoint_is_reachable(client, auth_headers):
    """POST /api/session/timing_event returns 200 (no host WS to push to in test)."""
    resp = client.post("/api/session/timing_event",
                       json={"event": "recording_warning", "minutes_remaining": 30},
                       headers=auth_headers)
    assert resp.status_code == 200
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_daemon_timing.py -v
```

- [ ] **Step 3: Implement _check_daily_timing and integrate into daemon loop**

```python
def _check_daily_timing(now_time=None) -> str | None:
    from datetime import datetime, time
    if now_time is None:
        now_time = datetime.now().time()
    # Order matters: check midnight first (spans 23:59–00:01)
    if now_time >= time(23, 59) or now_time < time(0, 1):
        return "midnight"
    # auto_pause uses threshold (>= 18:00), deduplication prevents re-firing
    if now_time >= time(18, 0):
        return "auto_pause"
    if now_time >= time(17, 30):
        return "warning"
    return None
```

Add to daemon loop. Use a date-aware fired tracker so it auto-resets on date change:

```python
_timing_fired_date = None   # date on which events were last fired
_timing_fired_today = set()

# In the daemon main loop, each iteration:
today = datetime.now().date()
if _timing_fired_date != today:
    _timing_fired_date = today
    _timing_fired_today = set()

timing = _check_daily_timing()
if timing == "warning" and "warning" not in _timing_fired_today:
    _timing_fired_today.add("warning")
    try:
        requests.post(f"{SERVER_URL}/api/session/timing_event",
                      json={"event": "recording_warning", "minutes_remaining": 30},
                      auth=_auth(), timeout=5)
    except Exception as e:
        logger.error(f"Failed to send warning event: {e}")

elif timing == "auto_pause" and "auto_pause" not in _timing_fired_today:
    _timing_fired_today.add("auto_pause")
    if current_session_folder and daemon_state.get("main", {}).get("status") == "active":
        daemon_state["main"]["status"] = "paused"
        _save_daemon_state(sessions_root, daemon_state)
        requests.post(f"{SERVER_URL}/api/session/pause", auth=_auth(), timeout=5)
        logger.info("Auto-paused recording at 18:00")

elif timing == "midnight" and "midnight" not in _timing_fired_today:
    _timing_fired_today.add("midnight")
    if daemon_state.get("main"):
        daemon_state["main"]["status"] = "ended"
    _save_daemon_state(sessions_root, daemon_state)
    logger.info("Session marked as ended at midnight")
```

Add `POST /api/session/timing_event` endpoint in `routers/session.py`:

```python
class TimingEventBody(BaseModel):
    event: str
    minutes_remaining: int | None = None

@router.post("/api/session/timing_event")
async def timing_event(body: TimingEventBody, credentials: HTTPBasicCredentials = Depends(verify_credentials)):
    """Daemon notifies server of a time-based event; server pushes it to the host WS."""
    host_ws = state.participants.get("__host__")
    if host_ws:
        try:
            await host_ws.send_json({
                "type": "timing_event",
                "event": body.event,
                "minutes_remaining": body.minutes_remaining,
            })
        except Exception:
            pass
    return {"ok": True}
```

Add handler in `static/host.js` (in the WebSocket `onmessage` handler):

```javascript
if (msg.type === 'timing_event' && msg.event === 'recording_warning') {
  const banner = document.getElementById('recording-warning-banner');
  const countdown = document.getElementById('recording-warning-countdown');
  if (banner) {
    if (countdown) countdown.textContent = msg.minutes_remaining ?? 30;
    banner.style.display = 'block';
    // Auto-hide the warning banner after 6pm passes (when recording-paused state takes over)
  }
}

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_daemon_timing.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add training_daemon.py routers/session.py tests/test_daemon_timing.py
git commit -m "feat: daemon auto-pauses at 6pm with 5:30pm warning and midnight session end"
```

---

## Task 12: Conference mode switch → auto-creates talk folder

When the host switches to conference mode and no talk is active, auto-create the talk folder (but do NOT disconnect participants — that only happens on explicit START TALK).

**Files:**
- Modify: `main.py` (POST /api/mode handler)
- Modify: `training_daemon.py` (handle new "create_talk_folder" action)

- [ ] **Step 1: Write the test**

```python
def test_mode_switch_to_conference_queues_create_talk_folder(client, auth_headers):
    from state import state
    state.session_main = {"name": "2026-03-25 WS", "started_at": "...", "status": "active"}
    state.session_talk = None

    resp = client.post("/api/mode", json={"mode": "conference"}, headers=auth_headers)
    assert resp.status_code == 200
    assert state.mode == "conference"
    assert state.session_request == {"action": "create_talk_folder"}

def test_mode_switch_to_conference_no_request_if_talk_exists(client, auth_headers):
    from state import state
    state.session_talk = {"name": "2026-03-25 12:30 talk", "started_at": "...", "status": "active"}
    resp = client.post("/api/mode", json={"mode": "conference"}, headers=auth_headers)
    assert resp.status_code == 200
    assert state.session_request is None or state.session_request.get("action") != "create_talk_folder"
```

- [ ] **Step 2: Run to verify it fails**

```bash
python -m pytest tests/test_main.py -v -k "mode_switch"
```

- [ ] **Step 3: Update POST /api/mode in main.py**

```python
@app.post("/api/mode")
async def set_mode(body: ModeBody, credentials: HTTPBasicCredentials = Depends(verify_credentials)):
    state.mode = body.mode
    if body.mode == "conference" and state.session_talk is None:
        state.session_request = {"action": "create_talk_folder"}
    await broadcast_state()
    return {"ok": True}
```

- [ ] **Step 4: Handle create_talk_folder in daemon**

```python
elif action == "create_talk_folder":
    now = datetime.now()
    talk_name = f"{now.strftime('%Y-%m-%d %H:%M')} talk"
    talk_folder = sessions_root / talk_name
    talk_folder.mkdir(exist_ok=True)
    daemon_state["talk"] = {"name": talk_name, "started_at": now.isoformat(), "status": "active"}
    _save_daemon_state(sessions_root, daemon_state)
    current_session_folder = talk_folder
    # Sync to server without disconnecting participants (no "action" key in payload)
    sync_payload = {
        "main": daemon_state["main"],
        "talk": daemon_state["talk"],
        "discussion_points": _get_current_key_points(),
        "session_state": None,
    }
    requests.post(f"{SERVER_URL}/api/session/sync", json=sync_payload, auth=_auth(), timeout=10)
    logger.info(f"Created talk folder: {talk_name}")
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_main.py -v -k "mode"
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add main.py training_daemon.py tests/test_main.py
git commit -m "feat: conference mode switch auto-creates talk folder without disconnecting participants"
```

---

## Integration Smoke Test

After all tasks complete, run a full integration check:

- [ ] Start server: `python -m uvicorn main:app --reload --port 8000`
- [ ] Open host panel at `http://localhost:8000/host`
- [ ] Open participant page in two tabs
- [ ] Verify FRAGILE state shown when no session exists (daemon not connected)
- [ ] Start daemon: `python3 training_daemon.py`
- [ ] Verify session auto-opens if today's folder exists
- [ ] Vote in a poll, give a participant 100 points
- [ ] Restart server: kill uvicorn, start again
- [ ] Verify participant scores are restored after daemon reconnects (~5s)
- [ ] Click START TALK: verify participant tabs show "Session paused" overlay
- [ ] Click END TALK: verify participants reconnect with scores
- [ ] Run full test suite: `python -m pytest tests/ -v --ignore=tests/test_load.py`
