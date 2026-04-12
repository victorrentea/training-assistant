# Remove Session Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the legacy session stack/main/talk/PersistedSessionRef concepts. Sessions are flat — one active at a time, identified by `active_session_id`. No nesting, no stack.

**Architecture:** Remove the in-memory `session_stack: list[dict]` threaded through `__main__.py`. Replace with a simple `session_name: str | None` variable (the folder name of the active session). Remove `sync_session_to_server` (which builds `{main, talk}` payloads for Railway) and simplify to just sending `set_session_id` via `announce_session_id`. Remove `session_name` from Railway — it only needs `session_id`. Remove `session_main`/`session_name` from daemon HTTP responses and host.js/participant.js.

**Tech Stack:** Python (FastAPI, Pydantic), vanilla JS, YAML specs

---

## File Impact Summary

**Delete entirely:**
- None (all changes are removals within existing files)

**Modify (daemon core):**
- `daemon/persisted_models.py` — remove `PersistedSessionRef`, prune `PersistedGlobalState` and `PersistedSessionMeta`
- `daemon/session_state.py` — remove `daemon_state_to_stack`, `session_meta_to_stack`, `stack_to_daemon_state`, `sync_session_to_server`; simplify `announce_session_id`
- `daemon/session/state.py` — remove `_session_stack`, `get_session_stack`, simplify `set_active_session`
- `daemon/__main__.py` — replace `session_stack` with `session_name`, remove nested session logic, simplify all session actions
- `daemon/summary/loop.py` — remove `stack_to_daemon_state` import and call

**Modify (daemon routers):**
- `daemon/host_state_router.py` — remove `session_main`, `session_name`, `SessionMainPayload` from response; simplify `_get_session_name`, `_get_active_session_entry`
- `daemon/participant/router.py` — remove `session_main`, `session_name`, `SessionMainPayload` from response; remove `_get_session_name`
- `daemon/misc/state.py` — remove `session_main`, `session_name` fields
- `daemon/misc/router.py` — simplify `_get_session_name_for_feedback`
- `daemon/session/router.py` — remove `start_talk`/`end_talk`, simplify `get_session_active`

**Modify (Railway):**
- `railway/features/ws/router.py` — remove `session_name` handling from `_handle_set_session_id`
- `railway/shared/state.py` — remove `session_name` field

**Modify (frontend):**
- `static/host.js` — remove `sessionMain`, `sessionTalk`, `_sessionName`, intervals editing, `_syncSessionMain`, `renderSummarySessionWindows` cleanup
- `static/participant.js` — remove `session_name` handling

**Modify (docs/specs):**
- `docs/railway-ws.yaml` — remove `session_name` from `set_session_id`
- `docs/openapi.yaml` — remove `session_main`, `session_name` from host/participant responses

**Modify (tests):**
- `tests/daemon/test_daemon_state.py` — remove stack/talk tests, update sync tests
- `tests/test_broadcast_handler.py` — remove `session_name` assertions
- `tests/daemon/test_host_state_router.py` — update session entry test
- `tests/daemon/test_misc_router.py` — update feedback session name test

**Regenerate:**
- `DB.md` — via `python3 scripts/generate_db_md.py --output DB.md`
- `API.md` — via `python3 scripts/generate_apis_md.py --output API.md`

---

### Task 1: Prune persisted models, add field descriptions, remove dead fields

**Files:**
- Modify: `daemon/persisted_models.py:14-161`
- Modify: `daemon/session_state.py:10-14` (import)

- [ ] **Step 1: Remove PersistedSessionRef class and prune global/meta models**

In `daemon/persisted_models.py`:
- **Delete** `PersistedSessionRef` class entirely (lines 14-21).
- **PersistedGlobalState**: remove `session_id`, `main`, `talk`, `stack` — keep only `active_session_id` and `log_level`.
- **PersistedSessionMeta**: reduce to read-only projection — keep **only** `session_id`. Remove `started_at`, `paused_intervals`, `talk`. This model is only used by `load_session_meta` which extracts `_SESSION_META_KEYS = ("session_id",)` — the other fields were never read.
- **PersistedSessionState**: remove `session_name` (line 107) and `token_usage` (line 161) — both are dead (never written to disk anymore).

```python
# PersistedSessionRef class: DELETE entirely (lines 14-21)

# PersistedGlobalState becomes:
class PersistedGlobalState(PersistedModel):
    """Global daemon state persisted in `global-state.json`."""
    active_session_id: str | None = None
    log_level: str | None = None

# PersistedSessionMeta becomes (read-only projection of session-state.json):
# NOTE: safe to prune — save_session_meta() does read-modify-write on the full
# session-state.json file (via load_session_state + merge + save_session_state).
# PersistedSessionMeta is only used for INPUT VALIDATION, not as the output shape.
# The _SESSION_META_KEYS = ("session_id",) tuple already limits what gets merged.
# started_at and paused_intervals were only used by session_meta_to_stack() which
# we're deleting.
class PersistedSessionMeta(PersistedModel):
    """Read-only projection: extracts session identity from `session-state.json`."""
    session_id: str | None = None

# PersistedSessionState: remove session_name (line 107) and token_usage (line 161)
```

- [ ] **Step 2: Add Field(description=...) to non-obvious persisted model fields**

Add short descriptions to fields where the type alone is unclear. Focus on dict/list fields where the key semantics aren't obvious. Do NOT add descriptions to self-evident fields (e.g. `name: str`, `active: bool`).

The DB.md generator already renders `description` from JSON schema as `# comment` via `_schema_comment()` in `generate_apis_md.py:130-137` — no generator changes needed. Regenerating DB.md (Task 9) will pick up the descriptions automatically.

```python
# PersistedParticipant — all fields are self-evident, skip

# PersistedPollState:
class PersistedPollState(PersistedModel):
    """Poll snapshot persisted in session state."""
    definition: dict[str, Any] | None = Field(default=None, description="Poll question and options as shown to participants")
    active: bool | None = None
    correct_ids: list[str] = Field(default_factory=list, description="Option IDs marked as correct answers")
    opened_at: str | None = None
    timer_seconds: int | None = None
    timer_started_at: str | None = None
    votes: dict[str, Any] = Field(default_factory=dict, description="participant_uuid → chosen option ID(s)")

# PersistedWordCloudState:
class PersistedWordCloudState(PersistedModel):
    words: dict[str, int] = Field(default_factory=dict, description="word → submission count")
    word_order: list[str] = Field(default_factory=list, description="Words in submission order")
    topic: str | None = None

# PersistedCodeReviewState:
class PersistedCodeReviewState(PersistedModel):
    snippet: str | None = None
    language: str | None = None
    phase: str | None = Field(default=None, description="reviewing | revealed")
    selections: dict[str, list[int]] = Field(default_factory=dict, description="participant_uuid → selected line indices")
    confirmed: list[int] = Field(default_factory=list, description="Host-confirmed bug line indices")

# PersistedDebateState:
class PersistedDebateState(PersistedModel):
    statement: str | None = None
    phase: str | None = Field(default=None, description="side_selection | arguments | ai_cleanup | prep | live_debate | ended")
    sides: dict[str, str] = Field(default_factory=dict, description="participant_uuid → 'for' | 'against'")
    arguments: list[dict[str, Any]] = Field(default_factory=list, description="Submitted arguments [{participant_uuid, side, text}]")
    champions: dict[str, str] = Field(default_factory=dict, description="side → champion participant_uuid")
    auto_assigned: list[str] = Field(default_factory=list, description="UUIDs auto-assigned to a side")
    first_side: str | None = Field(default=None, description="Which side speaks first in live debate")
    round_index: int | None = None
    round_timer_seconds: int | None = None
    round_timer_started_at: str | None = None

# PersistedSessionState:
class PersistedSessionState(PersistedModel):
    session_id: str | None = Field(default=None, description="6-char alphanumeric join code")
    # session_name: REMOVED (dead field)
    saved_at: str | None = Field(default=None, description="ISO timestamp of last snapshot write")
    mode: str | None = Field(default=None, description="workshop | conference")
    activity: str | None = None
    current_activity: str | None = None
    participants: dict[str, PersistedParticipant] = Field(default_factory=dict, description="participant_uuid → identity/score")
    # ... (keep existing legacy fields as-is, they have exclude=True)
    qa: dict[str, Any] | None = None
    qa_questions: dict[str, dict[str, Any]] = Field(default_factory=dict, description="question_id → {text, author, upvoters, answered}")
    slides_current: dict[str, Any] | None = Field(default=None, description="{presentation_name, current_page}")
    # token_usage: REMOVED (dead field — no longer persisted)
```

- [ ] **Step 3: Update import in session_state.py**

In `daemon/session_state.py:10-14`, verify no code references `PersistedSessionRef` directly. Remove it from imports if present.

- [ ] **Step 4: Run tests to see what breaks**

Run: `arch -arm64 uv run --extra dev --extra daemon python3 -m pytest tests/daemon/test_daemon_state.py -x -q 2>&1 | tail -20`

Expected: Several failures in stack/talk-related tests. This is expected and will be fixed in Task 8.

- [ ] **Step 5: Commit**

```bash
git add daemon/persisted_models.py daemon/session_state.py
git commit -m "refactor(session): prune persisted models, add field descriptions, remove dead fields"
```

---

### Task 2: Remove stack conversion functions and simplify sync

**Files:**
- Modify: `daemon/session_state.py:33-40,347-531`
- Modify: `daemon/summary/loop.py:16,121`

- [ ] **Step 1: Simplify announce_session_id — remove session_name parameter**

In `daemon/session_state.py`, change `announce_session_id` to only send `session_id`:

```python
def announce_session_id(session_id: str) -> None:
    """Immediately notify Railway of a new session_id via WS."""
    if _ws_client and _ws_client.connected:
        _ws_client.send({"type": "set_session_id", "session_id": session_id})
```

- [ ] **Step 2: Delete stack conversion and sync functions**

Delete these functions entirely from `daemon/session_state.py`:
- `session_meta_to_stack` (lines 347-359)
- `daemon_state_to_stack` (lines 362-377)
- `stack_to_daemon_state` (lines 380-388)
- `sync_session_to_server` (lines 500-531)

- [ ] **Step 3: Update summary/loop.py**

In `daemon/summary/loop.py`, remove the import of `stack_to_daemon_state` (line 16) and the call to `save_daemon_state(sessions_root, stack_to_daemon_state(session_stack))` (line 121). Also remove the call to `sync_session_to_server` on line 122. The summary loop should just save key points and log — session sync is handled by the main loop.

Replace lines 121-122 with just:
```python
            save_key_points(session_folder, current_key_points, 0, s_date)
```

Also update the function signature to remove `session_stack` parameter and the `sync_session_to_server` import. Check all callers of `run_summary_cycle` in `__main__.py` and update them.

- [ ] **Step 4: Update callers of announce_session_id**

In `daemon/session/router.py`, update calls to `announce_session_id` to remove the `session_name` argument:
- Line 138: `announce_session_id(session_id, name)` → `announce_session_id(session_id)`
- Line 161: `announce_session_id(session_id, folder_name)` → `announce_session_id(session_id)`

- [ ] **Step 5: Commit**

```bash
git add daemon/session_state.py daemon/summary/loop.py daemon/session/router.py
git commit -m "refactor(session): remove stack conversion functions and sync_session_to_server"
```

---

### Task 3: Simplify daemon/session/state.py — remove session_stack

**Files:**
- Modify: `daemon/session/state.py`

- [ ] **Step 1: Remove _session_stack and get_session_stack**

Replace the entire file with:

```python
"""Shared session state accessible from the daemon session router.

The main orchestrator loop (`daemon/__main__.py`) updates these fields;
the session router reads them to serve the GET /api/session/active and
GET /api/session/folders endpoints.
"""
import threading
from pathlib import Path

_lock = threading.Lock()

_active_session_id: str | None = None
_active_session_name: str | None = None  # folder name of active session
_sessions_root: Path | None = None


def set_active_session(session_id: str | None, session_name: str | None) -> None:
    """Called by main loop whenever active session changes."""
    global _active_session_id, _active_session_name
    with _lock:
        _active_session_id = session_id
        _active_session_name = session_name


def set_sessions_root(root: Path) -> None:
    """Called by main loop at startup with the resolved sessions root path."""
    global _sessions_root
    with _lock:
        _sessions_root = root


def get_active_session_id() -> str | None:
    with _lock:
        return _active_session_id


def get_active_session_name() -> str | None:
    with _lock:
        return _active_session_name


def get_sessions_root() -> Path | None:
    with _lock:
        return _sessions_root
```

- [ ] **Step 2: Commit**

```bash
git add daemon/session/state.py
git commit -m "refactor(session): replace session_stack with session_name in shared state"
```

---

### Task 4: Rewrite session management in __main__.py

This is the largest task — replacing `session_stack: list[dict]` with `session_name: str | None`.

**Files:**
- Modify: `daemon/__main__.py` (many locations)

- [ ] **Step 1: Replace session_stack initialization (lines 810-846)**

Replace the entire block with:

```python
    # ── Session initialization ──
    sessions_root = _boot_sessions_root
    log.info("session", f"Sessions root: {sessions_root}")
    session_shared_state.set_sessions_root(sessions_root)
    _raw_state = _boot_state
    _active_session_id: str | None = None
    session_name: str | None = None  # folder name of active session

    if "main" in _raw_state or "stack" in _raw_state:
        # Legacy format — extract session_id only, ignore stack
        _active_session_id = _raw_state.get("session_id")
        if _active_session_id:
            _active_folder = find_session_folder_by_id(sessions_root, _active_session_id)
            if _active_folder:
                session_name = _active_folder.name
        log.info("session", "Migrated old daemon state format")
    elif "active_session_id" in _raw_state:
        _active_session_id = _raw_state.get("active_session_id")
        if _active_session_id:
            _active_folder = find_session_folder_by_id(sessions_root, _active_session_id)
            if _active_folder:
                session_name = _active_folder.name
```

- [ ] **Step 2: Update _bind_initial_session_folder call (line 847)**

Change the call to pass `session_name` instead of `session_stack`:
```python
    config, _ = _bind_initial_session_folder(config, sessions_root, session_name)
```

Update the `_bind_initial_session_folder` function signature (line 598) accordingly — it should accept `session_name: str | None` instead of `session_stack: list[dict]`. Update its body to check `if not session_name:` instead of `if not session_stack:`.

- [ ] **Step 3: Update _do_save_daemon_state (line 859)**

Change:
```python
    def _do_save_daemon_state():
        nonlocal pending_global_state
        nonlocal _active_session_id
        pending_global_state = _build_global_state()
        session_shared_state.set_active_session(_active_session_id, session_name)
```

- [ ] **Step 4: Update startup restore block (line 888+)**

Replace `if session_stack:` with `if session_name:` and update the restore logic to use `session_name` instead of `session_stack[-1]["name"]`.

- [ ] **Step 5: Update _flush_session_state_backup calls**

The function `_flush_session_state_backup` (line 101) takes `session_stack` param. Change its signature to accept `session_name: str | None` instead. Update body:
```python
def _flush_session_state_backup(
    *,
    sessions_root: Path,
    session_name: str | None,
    session_snapshot: dict | None,
    last_flushed_hash: str | None,
    force: bool = False,
) -> tuple[str | None, bool]:
    if not session_name or not isinstance(session_snapshot, dict):
        return last_flushed_hash, False
    target_folder = sessions_root / session_name
    # ... rest unchanged
```

Update all callers of `_flush_session_state_backup` to pass `session_name=session_name` instead of `session_stack=session_stack`.

- [ ] **Step 6: Update _build_runtime_session_snapshot**

Remove `session_stack` parameter. Replace `session_name = session_stack[-1]["name"] if session_stack else None` (line 201) with the `session_name` from the outer scope (pass it as a parameter or use nonlocal).

- [ ] **Step 7: Rewrite session "create" action (lines 1107-1217)**

Key changes:
- Replace `if not session_stack:` with `if not session_name:` (i.e., no active session → fresh session)
- Replace `session_stack.append(new_session)` with `session_name = name`
- Remove `sync_session_to_server` calls — replace with `announce_session_id(_active_session_id)` (which was already called by the session router pre-announcement)
- Keep the state clearing logic for fresh sessions

- [ ] **Step 8: Remove "start" (nested talk) action entirely (lines 1219-1241)**

Delete the `elif action == "start":` block. Nested sessions no longer exist.

- [ ] **Step 9: Simplify "end" action (lines 1243-1310)**

Remove the "nested session ended — restore parent" branch. Only keep the "main session ended — clear everything" path:

```python
                    elif action == "end" and session_name:
                        runtime_session_snapshot = _build_runtime_session_snapshot(
                            active_session_id=_active_session_id,
                            session_name=session_name,
                        )
                        last_session_state_hash, wrote = _flush_session_state_backup(
                            sessions_root=sessions_root,
                            session_name=session_name,
                            session_snapshot=runtime_session_snapshot,
                            last_flushed_hash=last_session_state_hash,
                            force=True,
                        )
                        if wrote:
                            log.info("session", f"Forced flush {SESSION_STATE_FILENAME} for {session_name}")
                        ended_folder = sessions_root / session_name
                        save_key_points(ended_folder, current_key_points, summary_watermark, session_start_date_from_meta(ended_folder))
                        current_key_points = []
                        summary_watermark = 0
                        config = dc_replace(config, session_folder=None, session_notes=None)
                        old_session_name = session_name
                        session_name = None
                        _active_session_id = None
                        from daemon import addon_bridge_client
                        addon_bridge_client.send_session_ended()
                        log.info("session", f"Ended: {old_session_name}")
                        _do_save_daemon_state()
                        if pending_global_state is None:
                            pending_global_state = _build_global_state()
                        last_global_state_hash, _ = _flush_global_state_backup(
                            sessions_root=sessions_root,
                            global_state=pending_global_state,
                            last_flushed_hash=last_global_state_hash,
                            force=True,
                        )
                        announce_session_id_cleared()
                        transcript_state.reset()
```

Note: We need a new `announce_session_id_cleared()` function or just send `{"type": "set_session_id"}` directly to clear Railway's session. Add to `session_state.py`:

```python
def announce_session_cleared() -> None:
    """Notify Railway that no session is active."""
    if _ws_client and _ws_client.connected:
        _ws_client.send({"type": "set_session_id"})
```

- [ ] **Step 10: Update "rename" action (lines 1312-1329)**

Replace `session_stack[-1]["name"]` with `session_name` and `session_stack[-1]["name"] = new_name` with `session_name = new_name`. Remove `sync_session_to_server` call — replace with `announce_session_id(_active_session_id)`.

- [ ] **Step 11: Update "pause" and "resume" actions (lines 1331-1363)**

These use `session_stack[-1]` for pause/resume interval tracking. The pause_session/resume_session helpers modify the session dict in-place. Since we no longer have a session dict in memory, pause/resume intervals should be tracked differently — or removed if not needed.

Check: are pause intervals used anywhere besides the session intervals editor in host.js (which sends to `/session/sync` — a route that doesn't exist)? If not, remove pause/resume entirely.

If pause intervals are still needed (e.g., for transcript time-windowing), store them in session-state.json directly via `save_session_meta`/`load_session_meta`.

For now, simplify to:
```python
                    elif action == "pause" and session_name:
                        _do_save_daemon_state()
                        log.info("session", f"Paused: {session_name}")

                    elif action == "resume" and session_name:
                        _do_save_daemon_state()
                        resume_folder = sessions_root / session_name
                        # ... keep the session-state.json self-heal logic
                        log.info("session", f"Resumed: {session_name}")
```

- [ ] **Step 12: Remove "create_talk_folder" action (lines 1365-1388)**

Delete the entire `elif action == "create_talk_folder":` block. Nested talks no longer exist.

- [ ] **Step 13: Update _resolve_session_folder_from_state (line 351)**

Change parameter from `session_stack: list[dict]` to `session_name: str | None`. Update body to check `if session_name:` and use `sessions_root / session_name` instead of `session_stack[-1].get("name")`.

- [ ] **Step 14: Update all remaining session_stack references**

Search for any remaining `session_stack` references in `__main__.py` and replace with `session_name`. Key locations:
- Periodic session-folder refresh loop
- Summary cycle calls
- Any place that reads `session_stack[-1]["name"]`

- [ ] **Step 15: Run daemon tests**

Run: `arch -arm64 uv run --extra dev --extra daemon python3 -m pytest tests/daemon/ -x -q 2>&1 | tail -20`

Fix any import errors or missing function references.

- [ ] **Step 16: Commit**

```bash
git add daemon/__main__.py daemon/session_state.py
git commit -m "refactor(session): replace session_stack with session_name in main loop"
```

---

### Task 5: Remove session_main/session_name from daemon routers and misc state

**Files:**
- Modify: `daemon/host_state_router.py:145-147,193-194,323-327,334-336`
- Modify: `daemon/participant/router.py:184-186,602-603,628-634`
- Modify: `daemon/misc/state.py:23-24,62-65`
- Modify: `daemon/misc/router.py:120-125`
- Modify: `daemon/session/router.py:183-199,204-210`

- [ ] **Step 1: Remove session_main and session_name from misc_state**

In `daemon/misc/state.py`, remove lines 23-24 (`session_main`, `session_name`). Remove them from `sync_from_restore` (lines 62-65) and `reset_for_new_session` (lines 157-158).

- [ ] **Step 2: Remove SessionMainPayload and session_main/session_name from host state response**

In `daemon/host_state_router.py`:
- Delete `SessionMainPayload` class (lines 145-147)
- Remove `session_main` and `session_name` from `HostStateResponse` model (lines 193-194)
- Remove `session_main` and `session_name` from the response dict construction
- Simplify `_get_session_name()` (lines 323-327) to use only `session_shared_state.get_active_session_name()`
- Simplify `_get_active_session_entry()` (lines 334-336) — return a dict with just `name` and `started_at` from session metadata, or None

- [ ] **Step 3: Remove session_main/session_name from participant router**

In `daemon/participant/router.py`:
- Delete `SessionMainPayload` class (lines 184-186)
- Remove `session_main` and `session_name` from response (lines 602-603)
- Delete `_get_session_name()` function (lines 628-634)

- [ ] **Step 4: Simplify _get_session_name_for_feedback in misc/router.py**

In `daemon/misc/router.py`, replace `_get_session_name_for_feedback()` (lines 120-125) with:
```python
def _get_session_name_for_feedback() -> str | None:
    return session_shared_state.get_active_session_name()
```

- [ ] **Step 5: Remove start_talk/end_talk endpoints and simplify get_session_active**

In `daemon/session/router.py`:
- Delete `start_talk` endpoint (lines 183-187)
- Delete `end_talk` endpoint (lines 190-199)
- Simplify `get_session_active` (lines 204-210) — remove `_is_session_active` helper, just check `active_session_id`:
```python
@public_router.get("/active", response_model=SessionActiveResponse)
async def get_session_active():
    """Public endpoint: returns the active session_id or null."""
    return SessionActiveResponse(session_id=session_state.get_active_session_id())
```

- [ ] **Step 6: Run tests**

Run: `arch -arm64 uv run --extra dev --extra daemon python3 -m pytest tests/daemon/ -x -q 2>&1 | tail -20`

- [ ] **Step 7: Commit**

```bash
git add daemon/host_state_router.py daemon/participant/router.py daemon/misc/state.py daemon/misc/router.py daemon/session/router.py
git commit -m "refactor(session): remove session_main/session_name from routers and misc state"
```

---

### Task 6: Remove session_name from Railway

**Files:**
- Modify: `railway/features/ws/router.py:78-91`
- Modify: `railway/shared/state.py:72`

- [ ] **Step 1: Remove session_name from Railway state**

In `railway/shared/state.py`, delete line 72 (`self.session_name`).

- [ ] **Step 2: Remove session_name handling from _handle_set_session_id**

In `railway/features/ws/router.py`, simplify `_handle_set_session_id` (lines 78-117):
- Remove lines 81, 88-91 (session_name handling)

```python
async def _handle_set_session_id(data: dict):
    """Daemon sets/changes active session. Drop stale host/participant connections."""
    new_id = data.get("session_id")
    old_id = state.session_id
    had_active_session = bool(old_id)

    state.session_id = new_id or None
    # ... rest of disconnect logic unchanged
```

- [ ] **Step 3: Commit**

```bash
git add railway/features/ws/router.py railway/shared/state.py
git commit -m "refactor(session): remove session_name from Railway state"
```

---

### Task 7: Clean up frontend JS

**Files:**
- Modify: `static/host.js:19-21,448-450,874-936,938-949,3699-3721`
- Modify: `static/participant.js:3292-3293`

- [ ] **Step 1: Remove session state variables from host.js**

In `static/host.js`:
- Remove `let sessionMain = null;` (line 19)
- Remove `let sessionTalk = null;` (line 20)
- Remove `let _sessionName = null;` (line 21)
- Remove `if (msg.session_main !== undefined) sessionMain = msg.session_main;` (line 448)
- Remove `if (msg.session_talk !== undefined) sessionTalk = msg.session_talk;` (line 449)
- Remove `if (msg.session_name !== undefined) _sessionName = msg.session_name || null;` (line 450)

- [ ] **Step 2: Remove _syncSessionMain and intervals editor**

Delete the `_syncSessionMain` function (lines 874-881) and `_renderSessionIntervalsEditor` function (lines 883-936).

- [ ] **Step 3: Simplify renderSummarySessionWindows**

The function at line 938 uses `sessionTalk || sessionMain`. Since these are removed, check if this function is still needed. If `renderSummarySessionWindows` depends on session interval data from the response, it needs to get it from elsewhere. If there's no source anymore, remove it or make it a no-op.

- [ ] **Step 4: Simplify renderSessionPanel**

At line 3699, `renderSessionPanel` uses `sessionMain` and `sessionTalk`. The title display (line 3719) falls back to `_sessionName`. Since these are gone, the title should come from elsewhere (e.g., from the `daemon_session_folder` field already in the response). Update to:
```javascript
const rawName = msg.daemon_session_folder || '';
```

- [ ] **Step 5: Remove session_name from participant.js**

Remove the `session_name` handling at lines 3292-3293.

- [ ] **Step 6: Commit**

```bash
git add static/host.js static/participant.js
git commit -m "refactor(session): remove sessionMain/sessionTalk/sessionName from frontend"
```

---

### Task 8: Update tests

**Files:**
- Modify: `tests/daemon/test_daemon_state.py`
- Modify: `tests/test_broadcast_handler.py`
- Modify: `tests/daemon/test_host_state_router.py`
- Modify: `tests/daemon/test_misc_router.py`

- [ ] **Step 1: Update test_daemon_state.py**

Delete these tests entirely (they test removed functions):
- `test_persisted_global_state_model_validates_new_and_legacy_shapes` — remove legacy shape part (lines 18-24)
- `test_load_daemon_state_returns_raw_old_main_talk_format` (lines 73-84)
- `test_load_daemon_state_returns_raw_old_stack_format` (lines 87-100)
- `test_session_meta_to_stack_with_talk` (lines 203-214)
- `test_session_meta_to_stack_without_talk` (lines 217-222)
- `test_session_meta_to_stack_ignores_ended_talk` (lines 225-234)
- `test_daemon_state_to_stack_filters_ended_main` (lines 239-246)
- `test_daemon_state_to_stack_filters_ended_talk_keeps_main` (lines 249-257)
- `test_daemon_state_to_stack_active_sessions_included` (lines 260-267)

Update these tests (they use `session_stack` or `sync_session_to_server`):
- `test_sync_session_includes_session_state_when_file_exists` (lines 272-317) — test that `announce_session_id` sends correct WS message
- `test_sync_session_no_session_state_key_when_none` (lines 320-348) — remove or adapt
- `test_resolve_session_folder_prefers_active_stack_folder` (lines 383-407) — update to use `session_name` instead of `stack`
- `test_flush_session_state_backup_*` tests — update to use `session_name` param

- [ ] **Step 2: Update test_broadcast_handler.py**

In `tests/test_broadcast_handler.py`, remove `session_name` from mock state and assertions:
- Line 94: Remove `mock_state.session_name = "Old Session"`
- Line 105: Remove `assert mock_state.session_name is None`

- [ ] **Step 3: Update test_host_state_router.py**

In `tests/daemon/test_host_state_router.py`, update `test_build_slides_log_fields_uses_active_session_entry` to use `get_active_session_name()` instead of `get_session_stack()`.

- [ ] **Step 4: Update test_misc_router.py**

In `tests/daemon/test_misc_router.py`, update feedback tests that reference `_get_session_name_for_feedback`.

- [ ] **Step 5: Run all daemon tests**

Run: `arch -arm64 uv run --extra dev --extra daemon python3 -m pytest tests/daemon/ -x -q`

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add tests/
git commit -m "test(session): update tests for session stack removal"
```

---

### Task 9: Update docs and regenerate

**Files:**
- Modify: `docs/railway-ws.yaml`
- Regenerate: `DB.md`, `API.md`

- [ ] **Step 1: Remove session_name from railway-ws.yaml**

In `docs/railway-ws.yaml`, remove `session_name` property from `set_session_id` message (lines 214-216).

- [ ] **Step 2: Regenerate DB.md**

Run: `python3 scripts/generate_db_md.py --output DB.md`

This will auto-reflect the model changes from Task 1.

- [ ] **Step 3: Regenerate API.md**

Run: `python3 scripts/generate_apis_md.py --output API.md`

This will auto-reflect the response model changes from Task 5.

- [ ] **Step 4: Run contract tests**

Run: `arch -arm64 uv run --extra dev --extra daemon python3 -m pytest tests/daemon/test_api_contract.py tests/daemon/test_ws_contract.py tests/daemon/test_railway_ws_contract.py -x -q`

Expected: All pass (contracts match updated code).

- [ ] **Step 5: Run full test suite**

Run: `arch -arm64 uv run --extra dev --extra daemon bash tests/check-all.sh`

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add docs/railway-ws.yaml DB.md API.md docs/openapi.yaml
git commit -m "docs(session): update specs and regenerate DB.md/API.md after stack removal"
```

---

### Task 10: Final verification and push

- [ ] **Step 1: Run full pre-push checks**

Run: `arch -arm64 uv run --extra dev --extra daemon bash tests/check-all.sh`

Expected: All checks pass — daemon tests, contract tests, architecture contracts, C4 freshness, lint.

- [ ] **Step 2: Push to master**

```bash
git push origin master
```
