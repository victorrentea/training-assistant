# Phase 4c: Poll + Scores + Leaderboard Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate poll voting/scoring/timer, scores (global authority), and leaderboard from Railway to daemon. Daemon becomes the single score authority with Railway keeping a read-only mirror.

**Architecture:** Daemon holds all poll state and scores. Participant votes are REST calls proxied via Railway. Host poll/leaderboard management hits daemon localhost. Railway keeps `state.scores` as read-only mirror (updated by `scores_updated` broadcast) for unmigrated features. Quiz integration calls poll state directly.

**Tech Stack:** Python 3.12, FastAPI, Starlette TestClient, pytest, unittest.mock, websockets, asyncio

**Spec:** `docs/superpowers/specs/2026-04-04-poll-scores-migration-design.md`

---

## Context

Phase 4a/4b established patterns: daemon state cache singletons with threading lock, participant + host routers, write-back events via `X-Write-Back-Events` header, `_ws_client.send()` for host-direct broadcasts, `send_to_host()` for host browser push. This plan follows those patterns exactly.

### Key files to reference for patterns
- `daemon/wordcloud/state.py` + `daemon/wordcloud/router.py` — state cache + router pattern
- `daemon/qa/state.py` + `daemon/qa/router.py` — state cache with scoring + host push
- `daemon/proxy_handler.py` — write-back event extraction
- `features/ws/router.py` — broadcast handler, daemon message handlers, state push
- `tests/daemon/test_wordcloud_router.py` — test fixture pattern

### Design decisions (from spec)
- No backward compatibility — delete old code, produce final architecture
- No live vote counts during voting — results only after poll closes
- Votes are final for single-select (server-enforced); multi-select allows toggling
- Poll state is daemon-only — not in `daemon_state_push`, lost on daemon restart
- Scores: daemon is authority, Railway keeps read-only mirror updated by broadcast
- Leaderboard broadcast is unpersonalized — client computes own rank
- Codereview scoring: Railway sends `codereview_score_award` WS to daemon instead of mutating `state.scores`

---

## Task 1: Daemon scores module

**Files:**
- Create: `daemon/scores.py`
- Test: `tests/daemon/test_scores.py`

- [ ] **Step 1: Write tests for Scores**

```python
# tests/daemon/test_scores.py
import threading
from daemon.scores import Scores

class TestScores:
    def test_add_score(self):
        s = Scores()
        s.add_score("p1", 100)
        s.add_score("p1", 200)
        s.add_score("p2", 50)
        assert s.scores == {"p1": 300, "p2": 50}

    def test_snapshot(self):
        s = Scores()
        s.add_score("p1", 100)
        snap = s.snapshot()
        assert snap == {"p1": 100}
        snap["p1"] = 999  # mutation should not affect original
        assert s.scores["p1"] == 100

    def test_snapshot_base(self):
        s = Scores()
        s.add_score("p1", 100)
        s.snapshot_base()
        s.add_score("p1", 200)
        assert s.base_scores == {"p1": 100}
        assert s.scores == {"p1": 300}

    def test_reset(self):
        s = Scores()
        s.add_score("p1", 100)
        s.snapshot_base()
        s.reset()
        assert s.scores == {}
        assert s.base_scores == {}

    def test_sync_from_restore(self):
        s = Scores()
        s.add_score("p1", 100)
        s.sync_from_restore({"scores": {"p2": 200}, "base_scores": {"p2": 50}})
        assert s.scores == {"p2": 200}
        assert s.base_scores == {"p2": 50}

    def test_thread_safety(self):
        s = Scores()
        def add_many():
            for _ in range(1000):
                s.add_score("p1", 1)
        threads = [threading.Thread(target=add_many) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert s.scores["p1"] == 4000
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `pytest tests/daemon/test_scores.py -v`
Expected: ImportError — `daemon.scores` does not exist

- [ ] **Step 3: Implement `daemon/scores.py`**

```python
"""Global score authority — daemon owns all scoring."""
import threading


class Scores:
    def __init__(self):
        self._lock = threading.Lock()
        self.scores: dict[str, int] = {}
        self.base_scores: dict[str, int] = {}

    def add_score(self, pid: str, points: int):
        with self._lock:
            self.scores[pid] = self.scores.get(pid, 0) + points

    def snapshot_base(self):
        """Capture current scores as base (called when poll opens)."""
        with self._lock:
            self.base_scores = dict(self.scores)

    def reset(self):
        with self._lock:
            self.scores.clear()
            self.base_scores.clear()

    def sync_from_restore(self, data: dict):
        with self._lock:
            if "scores" in data:
                self.scores.clear()
                self.scores.update(data["scores"])
            if "base_scores" in data:
                self.base_scores.clear()
                self.base_scores.update(data.get("base_scores", {}))

    def snapshot(self) -> dict:
        return dict(self.scores)


scores = Scores()
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/daemon/test_scores.py -v`

- [ ] **Step 5: Commit**

```bash
git add daemon/scores.py tests/daemon/test_scores.py
git commit -m "feat(daemon): add global scores module with thread-safe operations"
```

---

## Task 2: Daemon poll state module

**Files:**
- Create: `daemon/poll/__init__.py`
- Create: `daemon/poll/state.py`
- Test: `tests/daemon/test_poll_state.py`

- [ ] **Step 1: Write tests for PollState**

Test cases needed:
- `test_create_poll` — creates poll object, clears previous state
- `test_create_poll_with_correct_count_zero` — `correct_count=0` handled via `is not None`
- `test_open_poll` — sets active, clears votes, snapshots base scores
- `test_close_poll` — returns vote_counts and total_votes
- `test_cast_vote_single_select` — accepts valid vote
- `test_cast_vote_single_select_final` — rejects second vote from same pid
- `test_cast_vote_multi_select` — accepts valid multi-vote
- `test_cast_vote_multi_select_toggle` — allows overwrite in multi-select
- `test_cast_vote_multi_select_over_limit` — rejects if more than correct_count
- `test_cast_vote_poll_closed` — rejects when poll_active is False
- `test_cast_vote_no_poll` — rejects when poll is None
- `test_cast_vote_invalid_option` — rejects unknown option_id
- `test_reveal_correct_speed_scoring` — fastest voter gets MAX_POINTS, slower gets less
- `test_reveal_correct_multi_proportional` — multi-select proportional scoring (R-W)/C
- `test_reveal_correct_no_votes` — no error when no votes cast
- `test_start_timer` — returns seconds + ISO started_at
- `test_clear` — resets all poll state
- `test_vote_counts_dirty_flag` — cache invalidated on new vote
- `test_append_to_quiz_md` — builds markdown from closed poll

Use a mock `Scores` object for `reveal_correct` tests.

- [ ] **Step 2: Run tests — expect FAIL**

Run: `pytest tests/daemon/test_poll_state.py -v`

- [ ] **Step 3: Implement `daemon/poll/state.py`**

Copy the `PollState` class from the spec (`docs/superpowers/specs/2026-04-04-poll-scores-migration-design.md` lines 90-308). Create `daemon/poll/__init__.py` (empty).

Key implementation notes:
- Use dirty flag for vote_counts cache (not len-based)
- Single-select: `if pid in self.votes: return False` (votes are final)
- Multi-select: allow overwrite (toggling)
- `correct_count is not None` (not `if correct_count:`)
- `reveal_correct` takes a `scores_obj` parameter — call `scores_obj.add_score()`

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/daemon/test_poll_state.py -v`

- [ ] **Step 5: Commit**

```bash
git add daemon/poll/ tests/daemon/test_poll_state.py
git commit -m "feat(daemon): add poll state module with speed-based scoring"
```

---

## Task 3: Daemon poll router (participant + host endpoints)

**Files:**
- Create: `daemon/poll/router.py`
- Test: `tests/daemon/test_poll_router.py`

- [ ] **Step 1: Write tests for poll router**

Follow the pattern from `tests/daemon/test_wordcloud_router.py`:

**Participant tests:**
- `test_cast_vote_single_select` — POST `/api/participant/poll/vote` with `{option_id}`, verify 200 + state updated
- `test_cast_vote_multi_select` — POST with `{option_ids}`, verify 200
- `test_cast_vote_rejected` — POST to closed poll, verify 409
- `test_cast_vote_no_participant_id` — missing header, verify 400

**Host tests:**
- `test_create_poll` — POST `/api/test-session/poll`, verify poll created + ws_client.send called with `poll_opened` broadcast (only if auto-open, otherwise just store)
- `test_open_poll` — POST `/api/test-session/poll/open`, verify poll_active + broadcast
- `test_close_poll` — POST `/api/test-session/poll/close`, verify poll deactivated + broadcast with vote_counts
- `test_reveal_correct` — PUT `/api/test-session/poll/correct`, verify scores computed + `poll_correct_revealed` and `scores_updated` broadcasts + `send_to_host` called
- `test_start_timer` — POST `/api/test-session/poll/timer`, verify broadcast with seconds + started_at
- `test_delete_poll` — DELETE `/api/test-session/poll`, verify state cleared + `poll_cleared` broadcast
- `test_get_quiz_md` — GET `/api/test-session/quiz-md`, verify returns markdown

Fixtures (following existing pattern):
```python
@pytest.fixture
def fresh_poll_state():
    ps = PollState()
    with patch("daemon.poll.router.poll_state", ps):
        yield ps

@pytest.fixture
def fresh_scores():
    s = Scores()
    with patch("daemon.poll.router.scores", s):
        yield s

@pytest.fixture
def mock_ws_client():
    mock = MagicMock()
    mock.send.return_value = True
    with patch("daemon.poll.router._ws_client", mock):
        yield mock

@pytest.fixture
def mock_host_ws():
    with patch("daemon.poll.router.send_to_host", new_callable=AsyncMock) as mock:
        yield mock
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `pytest tests/daemon/test_poll_router.py -v`

- [ ] **Step 3: Implement `daemon/poll/router.py`**

```python
"""Poll endpoints — participant (proxied via Railway) + host (daemon localhost)."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from daemon.poll.state import poll_state
from daemon.scores import scores
from daemon.host_ws import send_to_host

_ws_client = None

def set_ws_client(client):
    global _ws_client
    _ws_client = client

# --- Participant router (proxied via Railway) ---
participant_router = APIRouter(prefix="/api/participant/poll", tags=["poll"])

@participant_router.post("/vote")
async def cast_vote(request: Request):
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing participant ID"}, status_code=400)
    body = await request.json()
    option_id = body.get("option_id")
    option_ids = body.get("option_ids")
    accepted = poll_state.cast_vote(pid, option_id=option_id, option_ids=option_ids)
    if not accepted:
        return JSONResponse({"error": "Vote rejected"}, status_code=409)
    return JSONResponse({"ok": True})

# --- Host router (daemon localhost direct) ---
host_router = APIRouter(prefix="/api/{session_id}/poll", tags=["poll"])

@host_router.post("")
async def create_poll(request: Request):
    body = await request.json()
    question = body.get("question", "")
    options = body.get("options", [])
    multi = body.get("multi", False)
    correct_count = body.get("correct_count")
    source = body.get("source")
    page = body.get("page")
    # Activity gate — prevent creating poll when another activity is active
    from daemon.participant.state import participant_state
    activity = participant_state.current_activity
    if activity and activity not in ("none", "poll"):
        return JSONResponse({"error": f"Activity {activity} is active"}, status_code=409)
    poll = poll_state.create_poll(question, options, multi, correct_count, source, page)
    participant_state.current_activity = "poll"
    # Only notify host — participants see nothing until poll is opened
    await send_to_host({"type": "poll_created", "poll": poll})
    return JSONResponse({"ok": True, "poll": poll})

@host_router.post("/open")
async def open_poll(request: Request):
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)
    poll_state.open_poll(scores.snapshot_base)
    _broadcast({"type": "poll_opened", "poll": poll_state.poll})
    await send_to_host({"type": "poll_opened", "poll": poll_state.poll})
    return JSONResponse({"ok": True})

@host_router.post("/close")
async def close_poll(request: Request):
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)
    result = poll_state.close_poll()
    _broadcast({"type": "poll_closed", **result})
    await send_to_host({"type": "poll_closed", **result})
    return JSONResponse({"ok": True, **result})

@host_router.put("/correct")
async def reveal_correct(request: Request):
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)
    body = await request.json()
    correct_ids = body.get("correct_ids", [])
    result = poll_state.reveal_correct(correct_ids, scores)
    _broadcast({"type": "poll_correct_revealed", **result})
    _broadcast({"type": "scores_updated", "scores": result["scores"]})
    await send_to_host({"type": "poll_correct_revealed", **result})
    await send_to_host({"type": "scores_updated", "scores": result["scores"]})
    return JSONResponse({"ok": True})

@host_router.post("/timer")
async def start_timer(request: Request):
    if not poll_state.poll:
        return JSONResponse({"error": "No poll"}, status_code=400)
    body = await request.json()
    seconds = body.get("seconds", 30)
    result = poll_state.start_timer(seconds)
    _broadcast({"type": "poll_timer_started", **result})
    await send_to_host({"type": "poll_timer_started", **result})
    return JSONResponse({"ok": True})

@host_router.delete("")
async def delete_poll(request: Request):
    poll_state.clear()
    from daemon.participant.state import participant_state
    participant_state.current_activity = "none"
    _broadcast({"type": "poll_cleared"})
    _broadcast({"type": "activity_updated", "current_activity": "none"})
    await send_to_host({"type": "poll_cleared"})
    return JSONResponse({"ok": True})

# --- Quiz history (public) ---
quiz_md_router = APIRouter(tags=["quiz"])

@quiz_md_router.get("/api/{session_id}/quiz-md")
async def get_quiz_md():
    return JSONResponse({"content": poll_state.quiz_md_content})

# --- Broadcast helper ---
def _broadcast(event: dict):
    if _ws_client:
        _ws_client.send({"type": "broadcast", "event": event})
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/daemon/test_poll_router.py -v`

- [ ] **Step 5: Commit**

```bash
git add daemon/poll/router.py tests/daemon/test_poll_router.py
git commit -m "feat(daemon): add poll router with participant vote + host CRUD endpoints"
```

---

## Task 4: Daemon leaderboard router

**Files:**
- Create: `daemon/leaderboard/__init__.py`
- Create: `daemon/leaderboard/router.py`
- Test: `tests/daemon/test_leaderboard_router.py`

- [ ] **Step 1: Write tests for leaderboard router**

Test cases:
- `test_show_leaderboard` — POST `/api/test-session/leaderboard/show`, verify broadcast `leaderboard_revealed` with top-5 entries sorted by score + `send_to_host` called
- `test_show_leaderboard_with_names` — verify entries include name, score, uuid
- `test_hide_leaderboard` — POST `/api/test-session/leaderboard/hide`, verify broadcast `leaderboard_hide`
- `test_reset_scores` — DELETE `/api/test-session/scores`, verify `scores.reset()` called + broadcast `scores_updated` with empty scores

Fixtures: fresh_scores, mock_ws_client, mock_host_ws, mock participant_state (for names).

- [ ] **Step 2: Run tests — expect FAIL**

Run: `pytest tests/daemon/test_leaderboard_router.py -v`

- [ ] **Step 3: Implement `daemon/leaderboard/router.py`**

```python
"""Leaderboard show/hide and score reset — host-facing endpoints."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from daemon.scores import scores
from daemon.participant.state import participant_state
from daemon.host_ws import send_to_host

_ws_client = None

def set_ws_client(client):
    global _ws_client
    _ws_client = client

router = APIRouter(prefix="/api/{session_id}", tags=["leaderboard"])

@router.post("/leaderboard/show")
async def show_leaderboard():
    # Build top-5 entries sorted by score desc
    all_scores = scores.snapshot()
    entries = [
        {
            "uuid": pid,
            "name": participant_state.participant_names.get(pid, "???"),
            "score": sc,
        }
        for pid, sc in sorted(all_scores.items(), key=lambda x: -x[1])
        if sc > 0
    ][:5]
    total = len([s for s in all_scores.values() if s > 0])
    payload = {"type": "leaderboard_revealed", "entries": entries, "total_participants": total}
    if _ws_client:
        _ws_client.send({"type": "broadcast", "event": payload})
    await send_to_host(payload)
    return JSONResponse({"ok": True})

@router.post("/leaderboard/hide")
async def hide_leaderboard():
    payload = {"type": "leaderboard_hide"}
    if _ws_client:
        _ws_client.send({"type": "broadcast", "event": payload})
    await send_to_host(payload)
    return JSONResponse({"ok": True})

@router.delete("/scores")
async def reset_scores():
    scores.reset()
    payload = {"type": "scores_updated", "scores": scores.snapshot()}
    if _ws_client:
        _ws_client.send({"type": "broadcast", "event": payload})
    await send_to_host(payload)
    return JSONResponse({"ok": True})
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/daemon/test_leaderboard_router.py -v`

- [ ] **Step 5: Commit**

```bash
git add daemon/leaderboard/ tests/daemon/test_leaderboard_router.py
git commit -m "feat(daemon): add leaderboard router with unpersonalized broadcast"
```

---

## Task 5: Wire new modules into daemon startup

**Files:**
- Modify: `daemon/__main__.py` (lines 320-357 — handler registrations and set_ws_client calls)
- Modify: `daemon/host_server.py` (lines 69-81 — router mounts)

- [ ] **Step 1: Wire poll + leaderboard routers in `daemon/host_server.py`**

Add imports and mount routers following the pattern at lines 73-81:
```python
from daemon.poll.router import participant_router as poll_participant_router
from daemon.poll.router import host_router as poll_host_router
from daemon.poll.router import quiz_md_router
from daemon.leaderboard.router import router as leaderboard_router

app.include_router(poll_participant_router)
app.include_router(poll_host_router)
app.include_router(quiz_md_router)
app.include_router(leaderboard_router)
```

- [ ] **Step 2: Wire `set_ws_client` and state push in `daemon/__main__.py`**

Add to imports and initialization (following pattern at lines 336-357):
```python
from daemon.poll.router import set_ws_client as set_poll_ws
from daemon.leaderboard.router import set_ws_client as set_lb_ws
from daemon.scores import scores as daemon_scores
from daemon.poll.state import poll_state

# In set_ws_client calls section:
set_poll_ws(ws_client)
set_lb_ws(ws_client)

# Note: do NOT add daemon_scores.sync_from_restore to _handle_daemon_state_push.
# Daemon owns scores — syncing from Railway's stale mirror would corrupt them after WS reconnect.
# poll_state also has NO sync_from_restore — daemon owns poll state exclusively.
```

- [ ] **Step 3: Add `codereview_score_award` and `scores_reset` handlers**

Register handlers in `daemon/__main__.py`:
```python
def _handle_codereview_score_award(data):
    pids = data.get("participant_ids", [])
    points = data.get("points", 0)
    for pid in pids:
        daemon_scores.add_score(pid, points)
    payload = {"type": "scores_updated", "scores": daemon_scores.snapshot()}
    ws_client.send({"type": "broadcast", "event": payload})

def _handle_scores_reset(data):
    daemon_scores.reset()
    payload = {"type": "scores_updated", "scores": daemon_scores.snapshot()}
    ws_client.send({"type": "broadcast", "event": payload})

ws_client.register_handler("codereview_score_award", _handle_codereview_score_award)
ws_client.register_handler("scores_reset", _handle_scores_reset)
```

- [ ] **Step 4: Run daemon tests to verify no breakage**

Run: `pytest tests/daemon/ -v --tb=short`

- [ ] **Step 5: Commit**

```bash
git add daemon/__main__.py daemon/host_server.py
git commit -m "feat(daemon): wire poll, leaderboard, and scores into daemon startup"
```

---

## Task 6: Update Q&A and wordcloud routers to use daemon scores

**Files:**
- Modify: `daemon/qa/router.py` (lines 51-54, 79-83 — score_award write-backs)
- Modify: `daemon/wordcloud/router.py` (lines 46-50 — score_award + state_sync write-backs)

- [ ] **Step 1: Update Q&A router**

In `daemon/qa/router.py`:
- Add imports: `from daemon.scores import scores` and `from daemon.host_ws import send_to_host`
- In `submit_question` (line 51-54): remove `score_award` write-back, call `scores.add_score(pid, 100)` directly, add `scores_updated` broadcast to write-back events, and `await send_to_host({"type": "scores_updated", "scores": scores.snapshot()})`
- In `upvote_question` (line 79-83): remove both `score_award` write-backs, call `scores.add_score(author_pid, 50)` and `scores.add_score(pid, 25)` directly, add `scores_updated` broadcast, `send_to_host`

Updated write-back events for submit:
```python
scores.add_score(pid, 100)
request.state.write_back_events = [
    {"type": "broadcast", "event": {"type": "qa_updated", "questions": questions}},
    {"type": "broadcast", "event": {"type": "scores_updated", "scores": scores.snapshot()}},
]
await send_to_host({"type": "scores_updated", "scores": scores.snapshot()})
```

- [ ] **Step 2: Update wordcloud router**

In `daemon/wordcloud/router.py`:
- Add import: `from daemon.scores import scores`
- In `submit_word` (line 46-50): remove `score_award` and `wordcloud_state_sync` write-backs, call `scores.add_score(pid, 200)` directly, add `scores_updated` broadcast

Updated write-back events:
```python
scores.add_score(pid, 200)
request.state.write_back_events = [
    {"type": "broadcast", "event": {"type": "wordcloud_updated", **snapshot}},
    {"type": "broadcast", "event": {"type": "scores_updated", "scores": scores.snapshot()}},
]
```

For host word submission (if it awards points), same pattern using `_ws_client.send()`.

- [ ] **Step 3: Run existing Q&A and wordcloud tests**

Run: `pytest tests/daemon/test_qa_router.py tests/daemon/test_wordcloud_router.py -v`
Fix any test assertions that check for old `score_award` write-back events.

- [ ] **Step 4: Commit**

```bash
git add daemon/qa/router.py daemon/wordcloud/router.py
git commit -m "refactor(daemon): switch Q&A and wordcloud from score_award write-back to direct daemon scores"
```

---

## Task 7: Update quiz integration to call poll state directly

**Files:**
- Modify: `daemon/quiz/poll_api.py` (full rewrite — lines 1-85)

- [ ] **Step 1: Rewrite `daemon/quiz/poll_api.py`**

Replace WS message sends with direct poll state calls:

```python
"""Helpers for quiz → poll integration. Calls daemon poll state directly."""
from daemon.poll.state import poll_state
from daemon.scores import scores
from daemon import log

_ws_client = None

def set_ws_client(client):
    global _ws_client
    _ws_client = client

def post_poll(quiz: dict) -> None:
    """Create poll from quiz data."""
    question = quiz["question"]
    if quiz.get("source"):
        question += f"\n\n(Source: {quiz['source']}, p. {quiz.get('page', 'N/A')})"

    poll = poll_state.create_poll(
        question=question,
        options=quiz["options"],
        multi=len(quiz.get("correct_indices", [])) > 1,
    )
    if _ws_client and _ws_client.connected:
        _ws_client.send({"type": "broadcast", "event": {"type": "poll_created", "poll": poll}})
    else:
        log.error("daemon", "Cannot broadcast poll: WS not connected")

def open_poll() -> None:
    """Open voting on current poll."""
    poll_state.open_poll(scores.snapshot_base)
    if _ws_client and _ws_client.connected:
        _ws_client.send({"type": "broadcast", "event": {"type": "poll_opened", "poll": poll_state.poll}})
    else:
        log.error("daemon", "Cannot broadcast poll open: WS not connected")

def fetch_quiz_history() -> str:
    """Return accumulated closed polls as markdown."""
    return poll_state.quiz_md_content.strip()
```

Remove `post_status`, `fetch_summary_points` if they're handled elsewhere, or keep if still needed. Check callers in `daemon/quiz/generator.py`.

- [ ] **Step 2: Update callers**

Check `daemon/quiz/generator.py` for calls to `post_poll`, `open_poll`, `fetch_quiz_history`, `post_status`. Update import paths and function signatures (removed `config` parameter where not needed).

- [ ] **Step 3: Run quiz tests**

Run: `pytest tests/daemon/quiz/ -v`
Fix any broken tests due to changed signatures.

- [ ] **Step 4: Commit**

```bash
git add daemon/quiz/poll_api.py daemon/quiz/generator.py
git commit -m "refactor(daemon): quiz creates polls via direct state calls instead of WS messages"
```

---

## Task 8: Railway — add scores mirror handler + remove old handlers

**Files:**
- Modify: `features/ws/router.py` (lines 625-673 — handlers and handler map)
- Modify: `features/ws/daemon_protocol.py` (constants)

- [ ] **Step 1: Add `_handle_scores_updated` handler in `features/ws/router.py`**

```python
async def _handle_scores_updated(data: dict):
    """Update Railway's read-only score mirror from daemon broadcast."""
    event = data.get("event", {})
    if event.get("type") == "scores_updated" and "scores" in event:
        state.scores = event["scores"]
```

This handler processes broadcast events to keep the mirror in sync. Register it to run alongside `_handle_broadcast`:

In the daemon WS message loop, after calling `_handle_broadcast` for a broadcast message, also check if the inner event is `scores_updated` and call `_handle_scores_updated`.

Alternatively, add a hook inside `_handle_broadcast` that checks the event type:
```python
async def _handle_broadcast(data: dict):
    event = data.get("event")
    if not event:
        return
    # Update score mirror if this is a scores_updated broadcast
    if event.get("type") == "scores_updated" and "scores" in event:
        state.scores = {k: v for k, v in event["scores"].items()}
    # Fan out to all participants
    msg = json.dumps(event)
    for pid, ws in list(state.participants.items()):
        if pid.startswith("__"):
            continue
        try:
            await ws.send_text(msg)
        except Exception:
            pass
```

- [ ] **Step 2: Remove old handlers from `_DAEMON_MSG_HANDLERS`**

Remove these entries from the dict at lines 644-673:
- `MSG_POLL_CREATE: _handle_poll_create`
- `MSG_POLL_OPEN: _handle_poll_open`
- `MSG_SCORE_AWARD: _handle_score_award`
- `MSG_WORDCLOUD_STATE_SYNC: _handle_wordcloud_state_sync`

Delete the handler functions themselves:
- `_handle_poll_create` (lines 172-202)
- `_handle_poll_open` (lines 205-219)
- `_handle_score_award` (lines 635-641)
- `_handle_wordcloud_state_sync` (lines 625-632)

Add handler for `codereview_score_award` — this is a daemon→Railway→daemon pass-through. Actually, this goes the other direction: Railway sends `codereview_score_award` TO daemon, not FROM daemon. So it's not in `_DAEMON_MSG_HANDLERS`. The codereview router sends it directly via `state.daemon_ws.send_json()`.

- [ ] **Step 3: Remove poll + score fields from `daemon_state_push` (lines 708-726)**

Remove from the push payload:
- Any poll fields (check actual code — currently no poll fields in push)
- `scores` and `base_scores` — daemon owns scores; pushing Railway's stale mirror back to daemon on WS reconnect would corrupt authoritative score data

**Note on `_handle_participant_registered` (line 574-576):** This handler writes `state.scores.setdefault(pid, data["score"])`. This is acceptable — it only initializes scores for new participants (`.setdefault` doesn't overwrite existing values). The daemon sends the correct initial score. Leave it as-is.

- [ ] **Step 4: Remove vote/multi_vote WS handlers**

Remove from the participant WS message handler section:
- `_record_vote_and_broadcast()` helper (lines 58-69)
- `vote` handler block (lines 906-916)
- `multi_vote` handler block (lines 918-933)

- [ ] **Step 5: Remove unused imports and constants**

In `features/ws/daemon_protocol.py`, remove:
- `MSG_POLL_CREATE` (line 14)
- `MSG_POLL_OPEN` (line 15)
- `MSG_SCORE_AWARD` (line 68)
- `MSG_WORDCLOUD_STATE_SYNC` (line 65)

Remove corresponding imports in `features/ws/router.py`.

- [ ] **Step 6: Run Railway tests**

Run: `pytest tests/ -v --tb=short -k "not docker"`

- [ ] **Step 7: Commit**

```bash
git add features/ws/router.py features/ws/daemon_protocol.py
git commit -m "refactor: remove poll/score/wordcloud-sync handlers from Railway, add score mirror"
```

---

## Task 9: Railway — remove poll + leaderboard + scores files

**Files:**
- Delete: `features/poll/router.py`, `features/poll/state_builder.py`, `features/poll/__init__.py`
- Delete: `features/leaderboard/router.py`, `features/leaderboard/state_builder.py`, `features/leaderboard/__init__.py`
- Delete: `features/scores/router.py`, `features/scores/__init__.py`
- Modify: `main.py` (lines 26, 180, 185 — router mounts)
- Modify: `core/state.py` (remove poll fields, add_score, leaderboard_active)
- Modify: `core/messaging.py` (remove broadcast_leaderboard)
- Modify: `core/state_builder.py` (remove poll + leaderboard state builder registrations)

- [ ] **Step 1: Remove router mounts from `main.py`**

Remove:
- Poll router import and `app.include_router` (line 26, 180)
- Leaderboard router import and `app.include_router` (line 185)

Scores router is not mounted (already dead code), but verify.

- [ ] **Step 2: Delete feature files**

```bash
rm -rf features/poll/ features/leaderboard/ features/scores/
```

- [ ] **Step 3: Remove poll fields from `core/state.py`**

Remove from `__init__` (lines 33-79):
- `self.poll`, `self.poll_active`, `self.votes`, `self._vote_counts_cache`
- `self.poll_opened_at`, `self.poll_timer_seconds`, `self.poll_timer_started_at`
- `self.poll_correct_ids`, `self.vote_times`, `self.quiz_md_content`
- `self.leaderboard_active`
- `self.add_score()` method (lines 147-148)

**Keep:** `self.scores` and `self.base_scores` (read-only mirror).

Also remove `vote_counts()` method if it exists on AppState.

- [ ] **Step 4: Remove `broadcast_leaderboard` from `core/messaging.py`**

Delete the `broadcast_leaderboard` function (lines 132-150) and its lazy import of `_build_leaderboard_data`.

- [ ] **Step 5: Remove poll + leaderboard state builder registrations from `core/state_builder.py`**

Remove imports and registration calls for `features.poll.state_builder` and `features.leaderboard.state_builder`. Keep score reads (`state.scores.get(pid, 0)`) — they read from the mirror.

- [ ] **Step 6: Run tests**

Run: `pytest tests/ -v --tb=short -k "not docker"`
Fix any remaining import errors. Some tests in `tests/` may reference deleted modules — remove or update those tests.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: remove poll, leaderboard, scores feature packages from Railway"
```

---

## Task 10: Railway — update codereview + session to use daemon scores

**Files:**
- Modify: `features/codereview/router.py` (line 140 — score write)
- Modify: `features/session/router.py` (lines 203-204, 336-345 — score clear/restore)
- Modify: `features/snapshot/router.py` (lines 122-123 — score restore)
- Modify: `features/ws/router.py` (line 387 — state restore score write)

- [ ] **Step 1: Update codereview confirm-line**

In `features/codereview/router.py`, replace direct score mutation (line 140):
```python
# OLD:
state.scores[pid] = state.scores.get(pid, 0) + _CONFIRM_LINE_POINTS

# NEW:
# Send score award to daemon via WS
```

Replace the scoring block with:
```python
awarded_pids = [pid for pid, selected_lines in state.codereview_selections.items()
                if body.line in selected_lines]
if awarded_pids and state.daemon_ws:
    await state.daemon_ws.send_json({
        "type": "codereview_score_award",
        "participant_ids": awarded_pids,
        "points": _CONFIRM_LINE_POINTS,
    })
```

Remove the `await broadcast_state()` after scoring — daemon's `scores_updated` broadcast handles this. Keep the broadcast for codereview state if needed (check if the state builder sends codereview data).

- [ ] **Step 2: Update session reset**

In `features/session/router.py`, replace `state.scores.clear(); state.base_scores.clear()` (lines 203-204) with:
```python
if state.daemon_ws:
    await state.daemon_ws.send_json({"type": "scores_reset"})
```

Remove score restore from snapshot (lines 336-345) — daemon handles its own score persistence.

- [ ] **Step 3: Update snapshot restore**

In `features/snapshot/router.py`, remove score restore (lines 122-123). Keep score serialization in snapshot GET (reads from mirror — still useful for backup).

- [ ] **Step 4: Update state restore in ws/router.py**

In `features/ws/router.py`, remove `state.scores = restore_data["scores"]` from `_handle_state_restore` (line 387).

- [ ] **Step 5: Run tests**

Run: `pytest tests/ -v --tb=short -k "not docker"`

- [ ] **Step 6: Commit**

```bash
git add features/codereview/router.py features/session/router.py features/snapshot/router.py features/ws/router.py
git commit -m "refactor: codereview + session use daemon for scoring instead of local state"
```

---

## Task 11: Frontend — participant.js poll migration

**Files:**
- Modify: `static/participant.js` (lines 2814-2831, 2862-2863, 3925-3946)

- [ ] **Step 1: Switch vote sending from WS to REST**

In `castVote()` (lines 3925-3946), replace:
```javascript
// OLD:
sendWS('vote', { option_id: optionId });
sendWS('multi_vote', { option_ids: [...myVote] });

// NEW:
participantApi('poll/vote', { option_id: optionId });
participantApi('poll/vote', { option_ids: [...myVote] });
```

- [ ] **Step 2: Add broadcast event handlers**

In the WS message handler switch statement, add cases:
```javascript
case 'poll_opened':
    // Reset vote state, show poll
    currentPoll = msg.poll;
    pollActive = true;
    myVote = currentPoll.multi ? new Set() : null;
    pollResult = null;
    renderPollScreen();
    break;

case 'poll_closed':
    pollActive = false;
    // Show results with vote_counts
    renderPollResults(msg.vote_counts, msg.total_votes);
    break;

case 'poll_correct_revealed':
    // Extract own data from unpersonalized broadcast
    pollResult = {
        correct_ids: msg.correct_ids,
        voted_ids: msg.votes[myUUID] || [],
        score: (msg.scores[myUUID] || 0) - (myScoreBefore || 0),
    };
    renderPollResult(pollResult);
    break;

case 'poll_cleared':
    currentPoll = null;
    pollActive = false;
    renderPollScreen();
    break;

case 'poll_timer_started':
    startCountdown(msg.seconds, msg.started_at);
    break;

case 'scores_updated':
    myScore = msg.scores[myUUID] || 0;
    updateScoreDisplay();
    break;

case 'leaderboard_revealed':
    // Compute own rank from entries
    const myRank = msg.entries.findIndex(e => e.uuid === myUUID) + 1;
    showLeaderboard(msg.entries, msg.total_participants, myRank || null, myScore);
    break;

case 'leaderboard_hide':
    hideLeaderboard();
    break;
```

- [ ] **Step 3: Remove old handlers**

Remove handlers for:
- `vote_update` (lines 2814-2816) — no more live vote counts
- `result` (lines 2823-2831) — replaced by `poll_correct_revealed`
- `leaderboard` (lines 2862-2863) — replaced by `leaderboard_revealed`

- [ ] **Step 4: Test manually in browser**

Open participant page, verify:
- Poll appears when host creates/opens
- Voting works via REST
- Results show after close
- Correct answer reveal shows own score
- Leaderboard shows with own rank

- [ ] **Step 5: Commit**

```bash
git add static/participant.js
git commit -m "feat: switch participant poll/leaderboard from WS to REST + broadcast events"
```

---

## Task 12: Frontend — host.js poll + leaderboard migration

**Files:**
- Modify: `static/host.js` (lines 169, 1655, 1683, 1719, 1727, 1991, 3076, 3078)

- [ ] **Step 1: Switch poll API calls to daemon localhost**

All poll API calls in host.js currently use `fetch(API('/poll/...'))` where `API()` builds Railway URLs. Change to use daemon localhost:8081 URLs.

Check the host.js pattern — it may already have a `daemonApi()` helper or similar. If the host page loads from daemon localhost, the existing `API()` helper may already point to the right place. Verify and adjust.

- [ ] **Step 2: Switch leaderboard + score calls to daemon**

Change:
- `/leaderboard/show` → daemon localhost
- `/leaderboard/hide` → daemon localhost
- `DELETE /scores` → daemon localhost

- [ ] **Step 3: Add broadcast event handlers for host WS**

Add handlers in host WS message processing for:
- `poll_opened`, `poll_closed`, `poll_correct_revealed`, `poll_cleared`, `poll_timer_started`
- `scores_updated` — update score displays
- `leaderboard_revealed`, `leaderboard_hide`

These arrive via the host browser WS connection (daemon pushes directly via `send_to_host`).

- [ ] **Step 4: Test manually**

Open host panel at `localhost:8081/host/{session}`, verify:
- Create poll → broadcast to participants
- Open/close/reveal/timer all work
- Leaderboard show/hide works
- Score reset works

- [ ] **Step 5: Commit**

```bash
git add static/host.js
git commit -m "feat: switch host poll/leaderboard from Railway to daemon localhost"
```

---

## Task 13: Full integration test + cleanup

**Files:**
- Remove stale tests referencing deleted modules
- Run full test suite

- [ ] **Step 1: Find and fix broken tests**

Run: `pytest tests/ -v --tb=short -k "not docker" 2>&1 | head -100`

Look for:
- ImportError from `features.poll`, `features.leaderboard`, `features.scores`
- Tests that reference `state.add_score`, `state.poll`, `state.leaderboard_active`
- Tests checking for `score_award` write-back events

Fix or remove broken tests.

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v --tb=short -k "not docker"`
All tests must pass.

- [ ] **Step 3: Verify daemon starts cleanly**

Run: `python3 -c "from daemon.__main__ import *; print('imports OK')"`

- [ ] **Step 4: Commit any test fixes**

```bash
git add -A
git commit -m "test: fix tests for poll/scores/leaderboard migration"
```

---

## Task 14: Push to master

- [ ] **Step 1: Pull and rebase**

```bash
git fetch origin master && git rebase origin/master
```

- [ ] **Step 2: Run full test suite one more time**

Run: `pytest tests/ -v --tb=short -k "not docker"`

- [ ] **Step 3: Push**

```bash
git push origin master
```

- [ ] **Step 4: Verify production deployment**

Use the `wait-for-deploy` skill or check `/api/status` on production.

**Deployment note:** Tasks 8-12 (Railway removal + codereview/session changes + frontend) must be pushed together in a single push. Pushing Railway removal without the frontend changes would break the app. All 14 tasks accumulate commits locally, then push once at this step.
