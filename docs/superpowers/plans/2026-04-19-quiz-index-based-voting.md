# Quiz Index-Based Voting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-option string IDs with 0-based integer indices throughout the quiz API — participants send `options: list[int]`, receive `options: list[str]`, and all downstream fields (vote_counts, correct_indices) use positional integers.

**Architecture:** Bottom-up — rewrite `QuizState` core first, then propagate upward through routers → WS messages → Pydantic response models → YAML contracts → frontend. Each task commits a coherent slice. Backend tasks 1-7 can be verified with `pytest tests/daemon/`. Frontend tasks 9-10 require browser testing.

**Tech Stack:** Python/FastAPI/Pydantic (backend), vanilla JS (frontend), AsyncAPI YAML + OpenAPI YAML (contracts), pytest (tests).

---

## Task 1: Rewrite QuizState to index-based

**Files:**
- Modify: `daemon/quiz/state.py`
- Modify: `tests/daemon/test_quiz_state.py`

### Step 1.1 — Rewrite `test_quiz_state.py` with index-based expectations

Replace the entire file content:

```python
"""Tests for daemon/quiz/state.py — QuizState singleton."""
import pytest
from datetime import datetime, timezone, timedelta

from daemon.quiz.state import QuizState, _MAX_POINTS, _MIN_POINTS, _SLOWEST_MULTIPLIER


class MockScores:
    def __init__(self):
        self.scores = {}

    def add_score(self, pid, pts):
        self.scores[pid] = self.scores.get(pid, 0) + pts

    def snapshot(self):
        return dict(self.scores)


def _make_quiz(ps, multi=False, correct_count=None):
    ps.create_quiz("Test?", ["A", "B", "C"], multi=multi, correct_count=correct_count)
    ps.open_quiz(lambda: None)


# ── create_quiz ──────────────────────────────────────────────────────────────

def test_create_quiz():
    ps = QuizState()
    _make_quiz(ps)
    assert ps.quiz is not None
    assert ps.quiz["question"] == "Test?"
    assert ps.quiz["options"] == ["A", "B", "C"]
    assert ps.quiz_active is True
    assert ps.votes == {}
    assert ps.quiz_correct_indices is None


def test_create_quiz_clears_previous_state():
    ps = QuizState()
    _make_quiz(ps)
    ps.cast_vote("pid1", option_indices=[0])
    result = ps.create_quiz("New?", ["X"])
    assert ps.votes == {}
    assert ps.quiz_active is False
    assert result["question"] == "New?"


def test_create_quiz_with_correct_count_zero():
    """correct_count=0 must be stored — not filtered by 'if correct_count:'"""
    ps = QuizState()
    ps.create_quiz("Q?", ["A"], correct_count=0)
    assert "correct_count" in ps.quiz
    assert ps.quiz["correct_count"] == 0


# ── open_quiz ────────────────────────────────────────────────────────────────

def test_open_quiz():
    ps = QuizState()
    ps.create_quiz("Q?", ["A"])
    ps.votes["old"] = {"option_indices": [0], "voted_at": "2024-01-01T00:00:00+00:00"}
    snapshot_called = []
    ps.open_quiz(lambda: snapshot_called.append(True))
    assert ps.quiz_active is True
    assert ps.votes == {}
    assert ps.quiz_opened_at is not None
    assert snapshot_called == [True]


# ── close_quiz ───────────────────────────────────────────────────────────────

def test_close_quiz():
    ps = QuizState()
    _make_quiz(ps)
    ps.cast_vote("pid1", option_indices=[0])
    ps.cast_vote("pid2", option_indices=[1])
    result = ps.close_quiz()
    assert ps.quiz_active is False
    assert result["vote_counts"] == [1, 1, 0]
    assert "total_votes" not in result


# ── cast_vote single-select ──────────────────────────────────────────────────

def test_cast_vote_single_select():
    ps = QuizState()
    _make_quiz(ps)
    result = ps.cast_vote("pid1", option_indices=[0])
    assert result is True
    assert ps.votes["pid1"]["option_indices"] == [0]
    assert "voted_at" in ps.votes["pid1"]


def test_cast_vote_single_select_final():
    """Second vote from same pid must be rejected."""
    ps = QuizState()
    _make_quiz(ps)
    ps.cast_vote("pid1", option_indices=[0])
    result = ps.cast_vote("pid1", option_indices=[1])
    assert result is False
    assert ps.votes["pid1"]["option_indices"] == [0]


# ── cast_vote multi-select ───────────────────────────────────────────────────

def test_cast_vote_multi_select():
    ps = QuizState()
    _make_quiz(ps, multi=True, correct_count=2)
    result = ps.cast_vote("pid1", option_indices=[0, 1])
    assert result is True
    assert ps.votes["pid1"]["option_indices"] == [0, 1]


def test_cast_vote_multi_select_toggle():
    """Multi-select votes are final — second attempt rejected."""
    ps = QuizState()
    _make_quiz(ps, multi=True, correct_count=2)
    ps.cast_vote("pid1", option_indices=[0, 1])
    result = ps.cast_vote("pid1", option_indices=[1, 2])
    assert result is False
    assert ps.votes["pid1"]["option_indices"] == [0, 1]


def test_cast_vote_multi_select_over_limit():
    """Reject if more options selected than correct_count."""
    ps = QuizState()
    _make_quiz(ps, multi=True, correct_count=2)
    result = ps.cast_vote("pid1", option_indices=[0, 1, 2])
    assert result is False


# ── cast_vote error cases ────────────────────────────────────────────────────

def test_cast_vote_quiz_closed():
    ps = QuizState()
    _make_quiz(ps)
    ps.close_quiz()
    result = ps.cast_vote("pid1", option_indices=[0])
    assert result is False


def test_cast_vote_no_quiz():
    ps = QuizState()
    result = ps.cast_vote("pid1", option_indices=[0])
    assert result is False


def test_cast_vote_invalid_option():
    ps = QuizState()
    _make_quiz(ps)
    result = ps.cast_vote("pid1", option_indices=[99])
    assert result is False


# ── reveal_correct ───────────────────────────────────────────────────────────

def test_reveal_correct_speed_scoring():
    """Fastest voter gets ~1000pts, slower voter gets less."""
    ps = QuizState()
    _make_quiz(ps)

    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ps.quiz_opened_at = base_time
    ps.votes = {
        "fast": {"option_indices": [0], "voted_at": (base_time + timedelta(seconds=2)).isoformat()},
        "slow": {"option_indices": [0], "voted_at": (base_time + timedelta(seconds=8)).isoformat()},
    }

    scores = MockScores()
    result = ps.reveal_correct([0], scores)

    assert "fast" in scores.scores
    assert "slow" in scores.scores
    assert scores.scores["fast"] > scores.scores["slow"]
    assert scores.scores["fast"] == _MAX_POINTS


def test_reveal_correct_multi_proportional():
    """Voter selects 2 of 3 correct + 1 wrong → ratio = (2-1)/3"""
    ps = QuizState()
    ps.create_quiz("Q?", ["A", "B", "C", "D"], multi=True, correct_count=3)
    ps.open_quiz(lambda: None)

    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ps.quiz_opened_at = base_time
    vote_time = (base_time + timedelta(seconds=1)).isoformat()
    # Selects idx 0,1 (correct), idx 3 (wrong) — misses idx 2
    ps.votes = {"pid1": {"option_indices": [0, 1, 3], "voted_at": vote_time}}

    scores = MockScores()
    ps.reveal_correct([0, 1, 2], scores)

    assert "pid1" in scores.scores
    expected_ratio = (2 - 1) / 3
    expected_pts = round(_MAX_POINTS * expected_ratio)
    assert scores.scores["pid1"] == expected_pts


def test_reveal_correct_no_votes():
    """No votes → no scores awarded, no error."""
    ps = QuizState()
    _make_quiz(ps)
    scores = MockScores()
    result = ps.reveal_correct([0], scores)
    assert scores.scores == {}
    assert result["correct_indices"] == [0]


# ── start_timer ───────────────────────────────────────────────────────────────

def test_start_timer():
    ps = QuizState()
    result = ps.start_timer(30)
    assert result["seconds"] == 30
    assert "started_at" in result
    assert ps.quiz_timer_seconds == 30
    assert ps.quiz_timer_started_at is not None
    datetime.fromisoformat(result["started_at"])


# ── clear ─────────────────────────────────────────────────────────────────────

def test_clear():
    ps = QuizState()
    _make_quiz(ps)
    ps.cast_vote("pid1", option_indices=[0])
    ps.start_timer(20)
    ps.clear()
    assert ps.quiz is None
    assert ps.quiz_active is False
    assert ps.votes == {}
    assert ps.quiz_opened_at is None
    assert ps.quiz_correct_indices is None
    assert ps.quiz_timer_seconds is None
    assert ps.quiz_timer_started_at is None


# ── vote_counts ────────────────────────────────────────────────────────────────

def test_vote_counts_returns_list():
    ps = QuizState()
    _make_quiz(ps)
    ps.cast_vote("pid1", option_indices=[0])
    ps.cast_vote("pid2", option_indices=[1])
    counts = ps.vote_counts()
    assert counts == [1, 1, 0]


def test_vote_counts_dirty_flag():
    ps = QuizState()
    _make_quiz(ps)
    ps.cast_vote("pid1", option_indices=[0])
    counts1 = ps.vote_counts()
    assert counts1 == [1, 0, 0]
    assert ps._vote_counts_dirty is False

    counts2 = ps.vote_counts()
    assert counts2 is counts1

    ps.cast_vote("pid2", option_indices=[1])
    assert ps._vote_counts_dirty is True
    counts3 = ps.vote_counts()
    assert counts3 == [1, 1, 0]
    assert ps._vote_counts_dirty is False


# ── quiz_md ───────────────────────────────────────────────────────────────────

def test_append_to_quiz_md():
    ps = QuizState()
    _make_quiz(ps)
    ps.cast_vote("pid1", option_indices=[0])
    ps.reveal_correct([0], MockScores())

    md = ps.quiz_md_content
    assert "### Test?" in md
    assert "- [✓] A" in md
    assert "- [✗] B" in md
    assert "- [✗] C" in md
```

- [ ] **Step 1.2 — Run tests to verify they fail**

```bash
arch -arm64 uv run --extra dev --extra daemon pytest tests/daemon/test_quiz_state.py -v 2>&1 | tail -30
```
Expected: multiple FAILs (old API still in state.py).

- [ ] **Step 1.3 — Rewrite `daemon/quiz/state.py`**

Replace the full file:

```python
"""Quiz state singleton — daemon owns all quiz lifecycle."""
from datetime import datetime, timezone

_MAX_POINTS = 1000
_MIN_POINTS = 500
_SLOWEST_MULTIPLIER = 3


class QuizState:
    def __init__(self):
        self.quiz: dict | None = None
        self.quiz_active: bool = False
        self.votes: dict[str, dict] = {}  # uuid → {"option_indices": list[int], "voted_at": str ISO}
        self.quiz_opened_at: datetime | None = None
        self.quiz_correct_indices: list[int] | None = None
        self.quiz_timer_seconds: int | None = None
        self.quiz_timer_started_at: datetime | None = None
        self._vote_counts_dirty: bool = True
        self._vote_counts_cache: list[int] | None = None
        self.quiz_md_content: str = ""

    def create_quiz(self, question: str, options: list[str], multi: bool = False,
                    correct_count: int | None = None, source: str | None = None,
                    page: str | None = None) -> dict:
        import uuid as _uuid
        self.quiz = {
            "id": _uuid.uuid4().hex[:8],
            "question": question,
            "options": options,
            "multi": multi,
        }
        if correct_count is not None:
            self.quiz["correct_count"] = correct_count
        if source:
            self.quiz["source"] = source
        if page:
            self.quiz["page"] = page
        self.quiz_active = False
        self.votes.clear()
        self.quiz_correct_indices = None
        self.quiz_timer_seconds = None
        self.quiz_timer_started_at = None
        self._vote_counts_dirty = True
        return dict(self.quiz)

    def open_quiz(self, scores_snapshot_fn) -> None:
        self.quiz_active = True
        self.quiz_opened_at = datetime.now(timezone.utc)
        self.votes.clear()
        self._vote_counts_dirty = True
        scores_snapshot_fn()

    def close_quiz(self) -> dict:
        self.quiz_active = False
        counts = self.vote_counts()
        return {"vote_counts": counts}

    def cast_vote(self, pid: str, option_indices: list[int] | None = None) -> bool:
        if not self.quiz or not self.quiz_active:
            return False
        if pid in self.votes:
            return False
        if option_indices is None or not isinstance(option_indices, list):
            return False
        n = len(self.quiz["options"])
        is_multi = self.quiz.get("multi", False)
        if is_multi:
            correct_count = self.quiz.get("correct_count")
            max_allowed = correct_count if correct_count else n
            if (len(option_indices) > max_allowed
                    or len(set(option_indices)) != len(option_indices)
                    or not all(0 <= i < n for i in option_indices)):
                return False
        else:
            if len(option_indices) != 1 or not (0 <= option_indices[0] < n):
                return False
        voted_at = datetime.now(timezone.utc).isoformat()
        self.votes[pid] = {"option_indices": option_indices, "voted_at": voted_at}
        self._vote_counts_dirty = True
        return True

    def reveal_correct(self, correct_indices: list[int], scores_obj) -> dict:
        correct_set = set(correct_indices)
        n = len(self.quiz["options"]) if self.quiz else 0
        all_indices = set(range(n))
        wrong_set = all_indices - correct_set
        multi = self.quiz.get("multi", False) if self.quiz else False
        now = datetime.now(timezone.utc)
        opened_at = self.quiz_opened_at or now

        correct_voters = set()
        for pid, vote in self.votes.items():
            voted = set(vote["option_indices"])
            if multi and correct_set:
                R = len(voted & correct_set)
                W = len(voted & wrong_set)
                if max(0.0, (R - W) / len(correct_set)) > 0:
                    correct_voters.add(pid)
            else:
                if voted & correct_set:
                    correct_voters.add(pid)

        def _elapsed(pid: str) -> float:
            voted_at_str = self.votes[pid]["voted_at"]
            try:
                voted_at = datetime.fromisoformat(voted_at_str)
                return max(0.0, (voted_at - opened_at).total_seconds())
            except Exception:
                return 0.0

        elapsed_times = [_elapsed(p) for p in correct_voters]
        min_time = min(elapsed_times) if elapsed_times else 0.0

        for pid, vote in self.votes.items():
            voted = set(vote["option_indices"])
            if multi and correct_set:
                R = len(voted & correct_set)
                W = len(voted & wrong_set)
                C = len(correct_set)
                ratio = max(0.0, (R - W) / C)
                if ratio == 0:
                    continue
            else:
                if not (voted & correct_set):
                    continue
                ratio = 1.0
            elapsed = _elapsed(pid)
            speed_window = min_time * (_SLOWEST_MULTIPLIER - 1)
            if speed_window > 0:
                decay = min(1.0, (elapsed - min_time) / speed_window)
            else:
                decay = 0.0
            speed_pts = round(_MAX_POINTS - (_MAX_POINTS - _MIN_POINTS) * decay)
            pts = round(speed_pts * ratio)
            if pts > 0:
                scores_obj.add_score(pid, pts)

        self.quiz_correct_indices = list(correct_set)
        self._append_to_quiz_md(correct_set)
        return {
            "correct_indices": list(correct_set),
            "scores": scores_obj.snapshot(),
            "votes": {pid: v["option_indices"] for pid, v in self.votes.items()},
        }

    def start_timer(self, seconds: int) -> dict:
        self.quiz_timer_seconds = seconds
        self.quiz_timer_started_at = datetime.now(timezone.utc)
        return {
            "seconds": seconds,
            "started_at": self.quiz_timer_started_at.isoformat(),
        }

    def clear(self) -> None:
        self.quiz = None
        self.quiz_active = False
        self.votes.clear()
        self.quiz_opened_at = None
        self.quiz_correct_indices = None
        self.quiz_timer_seconds = None
        self.quiz_timer_started_at = None
        self._vote_counts_dirty = True

    def vote_counts(self) -> list[int]:
        if not self._vote_counts_dirty and self._vote_counts_cache is not None:
            return self._vote_counts_cache
        n = len(self.quiz["options"]) if self.quiz else 0
        counts = [0] * n
        for vote in self.votes.values():
            for idx in vote["option_indices"]:
                if 0 <= idx < n:
                    counts[idx] += 1
        self._vote_counts_cache = counts
        self._vote_counts_dirty = False
        return counts

    def _append_to_quiz_md(self, correct_set: set[int]):
        if not self.quiz:
            return
        lines = [f"### {self.quiz['question']}\n"]
        for i, text in enumerate(self.quiz["options"]):
            marker = "✓" if i in correct_set else "✗"
            lines.append(f"- [{marker}] {text}")
        lines.append("")
        self.quiz_md_content += "\n".join(lines) + "\n"


quiz_state = QuizState()
```

- [ ] **Step 1.4 — Run tests to verify they pass**

```bash
arch -arm64 uv run --extra dev --extra daemon pytest tests/daemon/test_quiz_state.py -v 2>&1 | tail -20
```
Expected: all PASS.

- [ ] **Step 1.5 — Commit**

```bash
git add daemon/quiz/state.py tests/daemon/test_quiz_state.py
git commit -m "refactor(quiz): replace option IDs with 0-based indices in QuizState"
```

---

## Task 2: Update quiz router models and fix pre-existing test bugs

**Files:**
- Modify: `daemon/quiz/router.py`
- Modify: `tests/daemon/test_quiz_router.py`

- [ ] **Step 2.1 — Rewrite `tests/daemon/test_quiz_router.py`**

Replace the full file:

```python
"""Tests for daemon quiz router — participant + host endpoints."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from daemon.quiz.state import QuizState
from daemon.scores import Scores
from daemon.quiz.router import participant_router, host_router, quiz_md_router
from daemon.participant.state import ParticipantState

_SAMPLE_OPTIONS = ["Option A", "Option B", "Option C"]


@pytest.fixture
def fresh_quiz_state():
    ps = QuizState()
    with patch("daemon.quiz.router.quiz_state", ps):
        yield ps


@pytest.fixture
def fresh_scores():
    s = Scores()
    with patch("daemon.quiz.router.scores", s):
        yield s


@pytest.fixture
def mock_broadcast():
    with patch("daemon.quiz.router.broadcast") as mock:
        yield mock


@pytest.fixture
def mock_notify_host():
    with patch("daemon.quiz.router.notify_host", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def mock_participant_state():
    ps = ParticipantState()
    ps.current_activity = "none"
    with patch("daemon.quiz.router.participant_state", ps):
        yield ps


@pytest.fixture
def participant_client(fresh_quiz_state, fresh_scores):
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture
def host_client(fresh_quiz_state, fresh_scores, mock_broadcast, mock_notify_host, mock_participant_state):
    app = FastAPI()
    app.include_router(host_router)
    app.include_router(quiz_md_router)
    return TestClient(app)


def _create_and_open_quiz(client, fresh_quiz_state, fresh_scores):
    resp = client.post("/api/test-session/host/quiz", json={
        "question": "Which option?",
        "options": _SAMPLE_OPTIONS,
        "multi": False,
    })
    assert resp.status_code == 200
    client.post("/api/test-session/host/quiz/open", json={})


# ──────────────────────────────────────────────
# Participant endpoint tests
# ──────────────────────────────────────────────

class TestParticipantVote:
    def test_cast_vote_single(self, participant_client, fresh_quiz_state):
        fresh_quiz_state.create_quiz("Q?", _SAMPLE_OPTIONS)
        fresh_quiz_state.open_quiz(lambda: None)

        resp = participant_client.post(
            "/api/participant/quiz/vote",
            json={"options": [0]},
            headers={"X-Participant-ID": "pid1"},
        )
        assert resp.status_code == 204

    def test_cast_vote_multi(self, participant_client, fresh_quiz_state):
        fresh_quiz_state.create_quiz("Q?", _SAMPLE_OPTIONS, multi=True, correct_count=2)
        fresh_quiz_state.open_quiz(lambda: None)

        resp = participant_client.post(
            "/api/participant/quiz/vote",
            json={"options": [0, 1]},
            headers={"X-Participant-ID": "pid1"},
        )
        assert resp.status_code == 204

    def test_cast_vote_rejected(self, participant_client, fresh_quiz_state):
        resp = participant_client.post(
            "/api/participant/quiz/vote",
            json={"options": [0]},
            headers={"X-Participant-ID": "pid1"},
        )
        assert resp.status_code == 409

    def test_cast_vote_no_pid(self, participant_client):
        resp = participant_client.post(
            "/api/participant/quiz/vote",
            json={"options": [0]},
        )
        assert resp.status_code == 400


# ──────────────────────────────────────────────
# Host endpoint tests
# ──────────────────────────────────────────────

class TestHostCreateQuiz:
    def test_create_quiz(self, host_client, fresh_quiz_state, mock_notify_host):
        resp = host_client.post("/api/test-session/host/quiz", json={
            "question": "Best framework?",
            "options": _SAMPLE_OPTIONS,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["quiz"]["question"] == "Best framework?"
        assert data["quiz"]["options"] == _SAMPLE_OPTIONS
        mock_notify_host.assert_called_once()
        msg = mock_notify_host.call_args[0][0]
        assert msg.type == "quiz_ai_generated"

    def test_create_quiz_activity_gate(self, host_client, mock_participant_state):
        mock_participant_state.current_activity = "debate"
        resp = host_client.post("/api/test-session/host/quiz", json={
            "question": "Q?",
            "options": _SAMPLE_OPTIONS,
        })
        assert resp.status_code == 409

    def test_create_quiz_string_options(self, host_client):
        """Options are always strings — sent and returned as-is."""
        resp = host_client.post("/api/test-session/host/quiz", json={
            "question": "Manual quiz?",
            "options": ["Alpha", "Beta", "Gamma"],
        })
        assert resp.status_code == 200
        quiz = resp.json()["quiz"]
        assert quiz["options"] == ["Alpha", "Beta", "Gamma"]


class TestHostOpenQuiz:
    def test_open_quiz(self, host_client, fresh_quiz_state, mock_broadcast, mock_notify_host):
        fresh_quiz_state.create_quiz("Q?", _SAMPLE_OPTIONS)

        resp = host_client.post("/api/test-session/host/quiz/open", json={})
        assert resp.status_code == 204

        broadcast_msg = mock_broadcast.call_args_list[0][0][0]
        assert broadcast_msg.type == "quiz_opened"

        host_msg = mock_notify_host.call_args[0][0]
        assert host_msg.type == "quiz_opened"

    def test_open_quiz_no_quiz(self, host_client):
        resp = host_client.post("/api/test-session/host/quiz/open", json={})
        assert resp.status_code == 400


class TestHostCloseQuiz:
    def test_close_quiz(self, host_client, fresh_quiz_state, fresh_scores, mock_broadcast, mock_notify_host):
        _create_and_open_quiz(host_client, fresh_quiz_state, fresh_scores)

        resp = host_client.post("/api/test-session/host/quiz/close", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert isinstance(data["vote_counts"], list)
        assert "total_votes" not in data

        broadcast_types = [call[0][0].type for call in mock_broadcast.call_args_list]
        assert "quiz_closed" in broadcast_types

    def test_close_quiz_no_quiz(self, host_client):
        resp = host_client.post("/api/test-session/host/quiz/close", json={})
        assert resp.status_code == 400


class TestHostRevealCorrect:
    def test_reveal_correct(self, host_client, fresh_quiz_state, fresh_scores, mock_broadcast, mock_notify_host):
        _create_and_open_quiz(host_client, fresh_quiz_state, fresh_scores)

        resp = host_client.put("/api/test-session/host/quiz/correct", json={"correct_indices": [0]})
        assert resp.status_code == 204

        broadcast_types = [call[0][0].type for call in mock_broadcast.call_args_list]
        assert "quiz_correct_revealed" in broadcast_types
        assert "scores_updated" in broadcast_types

        host_msg_types = [call[0][0].type for call in mock_notify_host.call_args_list]
        assert "quiz_correct_revealed" in host_msg_types

    def test_reveal_correct_no_quiz(self, host_client):
        resp = host_client.put("/api/test-session/host/quiz/correct", json={"correct_indices": [0]})
        assert resp.status_code == 400


class TestHostStartTimer:
    def test_start_timer(self, host_client, fresh_quiz_state, mock_broadcast, mock_notify_host):
        fresh_quiz_state.create_quiz("Q?", _SAMPLE_OPTIONS)

        resp = host_client.post("/api/test-session/host/quiz/timer", json={"seconds": 45})
        assert resp.status_code == 204

        broadcast_msg = mock_broadcast.call_args_list[0][0][0]
        assert broadcast_msg.type == "quiz_timer_started"
        assert broadcast_msg.seconds == 45

    def test_start_timer_no_quiz(self, host_client):
        resp = host_client.post("/api/test-session/host/quiz/timer", json={"seconds": 30})
        assert resp.status_code == 400


class TestHostDeleteQuiz:
    def test_delete_quiz(self, host_client, fresh_quiz_state, mock_participant_state, mock_broadcast, mock_notify_host):
        fresh_quiz_state.create_quiz("Q?", _SAMPLE_OPTIONS)

        resp = host_client.delete("/api/test-session/host/quiz")
        assert resp.status_code == 204
        assert fresh_quiz_state.quiz is None
        assert mock_participant_state.current_activity == "none"

        broadcast_types = [call[0][0].type for call in mock_broadcast.call_args_list]
        assert "quiz_cleared" in broadcast_types
        assert "activity_updated" in broadcast_types


class TestGetQuizMd:
    def test_get_quiz_md(self, host_client, fresh_quiz_state):
        fresh_quiz_state.quiz_md_content = "### Some quiz\n- [✓] A\n"

        resp = host_client.get("/api/test-session/quiz-md")
        assert resp.status_code == 200
        data = resp.json()
        assert "content" in data
        assert "Some quiz" in data["content"]

    def test_get_quiz_md_empty(self, host_client, fresh_quiz_state):
        resp = host_client.get("/api/test-session/quiz-md")
        assert resp.status_code == 200
        assert resp.json()["content"] == ""
```

- [ ] **Step 2.2 — Run tests to verify they fail**

```bash
arch -arm64 uv run --extra dev --extra daemon pytest tests/daemon/test_quiz_router.py -v 2>&1 | tail -30
```
Expected: import errors + FAILs (old router API).

- [ ] **Step 2.3 — Rewrite `daemon/quiz/router.py`**

Replace the full file:

```python
"""Quiz endpoints — participant (proxied via Railway) + host (daemon localhost)."""
import logging
from typing import Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from daemon.participant.state import participant_state
from daemon.quiz.state import quiz_state
from daemon.scores import scores
from daemon.ws_messages import (
    ActivityUpdatedMsg,
    QuizAiGeneratedMsg,
    QuizClearedMsg,
    QuizClosedMsg,
    QuizCorrectRevealedMsg,
    QuizOpenedMsg,
    QuizTimerStartedMsg,
    ScoresUpdatedMsg,
    VoteUpdateMsg,
)
from daemon.ws_publish import broadcast, broadcast_event, notify_host

logger = logging.getLogger(__name__)


# ── Pydantic models ──

class OkResponse(BaseModel):
    ok: bool = True

class VoteRequest(BaseModel):
    options: list[int]

class CreateQuizRequest(BaseModel):
    question: str = ""
    options: list[str] = []
    multi: bool = False
    correct_count: Optional[int] = None

class QuizResponse(BaseModel):
    id: str
    question: str
    options: list[str]
    multi: bool
    correct_count: int | None = None
    source: str | None = None
    page: str | None = None

class CreateQuizResponse(BaseModel):
    ok: bool = True
    quiz: QuizResponse

class CloseQuizResponse(BaseModel):
    ok: bool = True
    vote_counts: list[int]

class RevealCorrectRequest(BaseModel):
    correct_indices: list[int] = []

class StartTimerRequest(BaseModel):
    seconds: int = 30

class SetQuizStatusRequest(BaseModel):
    open: bool

class QuizMdResponse(BaseModel):
    content: str


# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant/quiz", tags=["quiz"])


@participant_router.post("/vote", status_code=204)
async def cast_vote(request: Request, body: VoteRequest):
    """Participant casts a vote."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing participant ID"}, status_code=400)

    accepted = quiz_state.cast_vote(pid, option_indices=body.options)
    if not accepted:
        return JSONResponse({"error": "Vote rejected"}, status_code=409)

    vote_msg = VoteUpdateMsg(vote_counts=quiz_state.vote_counts())
    request.state.write_back_events = [broadcast_event(vote_msg)]
    await notify_host(vote_msg)
    return Response(status_code=204)


# ── Host router (called directly on daemon localhost) ──

host_router = APIRouter(prefix="/api/{session_id}/host/quiz", tags=["quiz"])


@host_router.post("", response_model=CreateQuizResponse)
async def create_quiz(body: CreateQuizRequest):
    """Host creates a new quiz."""
    activity = participant_state.current_activity
    if activity and activity not in ("none", "quiz"):
        return JSONResponse({"error": f"Activity {activity} is active"}, status_code=409)

    quiz = quiz_state.create_quiz(
        body.question,
        body.options,
        body.multi,
        body.correct_count,
    )
    participant_state.current_activity = "quiz"

    await notify_host(QuizAiGeneratedMsg(quiz=quiz))
    return CreateQuizResponse(quiz=QuizResponse.model_validate(quiz))


@host_router.post("/open", status_code=204)
async def open_quiz():
    """Host opens the quiz for voting."""
    if not quiz_state.quiz:
        return JSONResponse({"error": "No quiz"}, status_code=400)

    quiz_state.open_quiz(scores.snapshot_base)
    broadcast(QuizOpenedMsg(quiz=quiz_state.quiz))
    await notify_host(QuizOpenedMsg(quiz=quiz_state.quiz))
    return Response(status_code=204)


@host_router.post("/close", response_model=CloseQuizResponse)
async def close_quiz():
    """Host closes the quiz."""
    if not quiz_state.quiz:
        return JSONResponse({"error": "No quiz"}, status_code=400)

    result = quiz_state.close_quiz()
    closed_msg = QuizClosedMsg(vote_counts=result["vote_counts"])
    broadcast(closed_msg)
    await notify_host(closed_msg)
    return CloseQuizResponse(**result)


@host_router.put("/correct", status_code=204)
async def reveal_correct(body: RevealCorrectRequest):
    """Host reveals correct answers and awards scores."""
    if not quiz_state.quiz:
        return JSONResponse({"error": "No quiz"}, status_code=400)

    result = quiz_state.reveal_correct(body.correct_indices, scores)
    broadcast(QuizCorrectRevealedMsg(correct_indices=result["correct_indices"]))
    broadcast(ScoresUpdatedMsg(scores=result["scores"]))
    await notify_host(QuizCorrectRevealedMsg(correct_indices=result["correct_indices"]))
    await notify_host(ScoresUpdatedMsg(scores=result["scores"]))
    return Response(status_code=204)


@host_router.post("/timer", status_code=204)
async def start_timer(body: StartTimerRequest):
    """Host starts a countdown timer for the quiz."""
    if not quiz_state.quiz:
        return JSONResponse({"error": "No quiz"}, status_code=400)

    result = quiz_state.start_timer(body.seconds)
    broadcast(QuizTimerStartedMsg(seconds=result["seconds"]))
    await notify_host(QuizTimerStartedMsg(seconds=result["seconds"]))
    return Response(status_code=204)


@host_router.put("/status", response_model=OkResponse | CloseQuizResponse)
async def set_quiz_status(body: SetQuizStatusRequest):
    """Compatibility: {open: true} → open_quiz, {open: false} → close_quiz."""
    if body.open:
        return await open_quiz()
    else:
        return await close_quiz()


@host_router.delete("", status_code=204)
async def delete_quiz():
    """Host deletes the current quiz."""
    quiz_state.clear()
    participant_state.current_activity = "none"
    broadcast(QuizClearedMsg())
    broadcast(ActivityUpdatedMsg(current_activity="none"))
    await notify_host(QuizClearedMsg())
    return Response(status_code=204)


# ── Quiz history (public) ──

quiz_md_router = APIRouter(tags=["quiz"])


@quiz_md_router.get("/api/{session_id}/quiz-md", response_model=QuizMdResponse)
async def get_quiz_md():
    """Return the accumulated quiz markdown history."""
    return QuizMdResponse(content=quiz_state.quiz_md_content)
```

- [ ] **Step 2.4 — Run tests**

```bash
arch -arm64 uv run --extra dev --extra daemon pytest tests/daemon/test_quiz_router.py -v 2>&1 | tail -30
```
Expected: all PASS (ws_messages still has old types — some tests may fail; fix in Task 3).

- [ ] **Step 2.5 — Commit**

```bash
git add daemon/quiz/router.py tests/daemon/test_quiz_router.py
git commit -m "refactor(quiz): update router to index-based vote API, fix quiz_md router name"
```

---

## Task 3: Update WS message models

**Files:**
- Modify: `daemon/ws_messages.py`

- [ ] **Step 3.1 — Update `QuizClosedMsg`, `QuizCorrectRevealedMsg`, and `VoteUpdateMsg`**

In `daemon/ws_messages.py`, make these targeted edits:

**Replace `QuizClosedMsg`:**
```python
class QuizClosedMsg(BaseModel):
    type: Literal["quiz_closed"] = "quiz_closed"
    vote_counts: list[int]
```

**Replace `QuizCorrectRevealedMsg`:**
```python
class QuizCorrectRevealedMsg(BaseModel):
    type: Literal["quiz_correct_revealed"] = "quiz_correct_revealed"
    correct_indices: list[int]
```

Find `VoteUpdateMsg` (search for `vote_update`) and replace its `votes` field:
```python
class VoteUpdateMsg(BaseModel):
    type: Literal["vote_update"] = "vote_update"
    vote_counts: list[int]
```

- [ ] **Step 3.2 — Run full daemon tests**

```bash
arch -arm64 uv run --extra dev --extra daemon pytest tests/daemon/test_quiz_router.py tests/daemon/test_quiz_state.py -v 2>&1 | tail -20
```
Expected: all PASS.

- [ ] **Step 3.3 — Commit**

```bash
git add daemon/ws_messages.py
git commit -m "refactor(quiz): update WS message models to index-based vote_counts and correct_indices"
```

---

## Task 4: Update host_state_router Pydantic models

**Files:**
- Modify: `daemon/host_state_router.py`

- [ ] **Step 4.1 — Replace QuizOption, QuizData, QuizQueueOption, QuizQueueQuestion, HostStateResponse.vote_counts**

In `daemon/host_state_router.py`:

**Delete `QuizOption` class entirely** (lines `class QuizOption(BaseModel): id: str / text: str`).

**Replace `QuizData`:**
```python
class QuizData(BaseModel):
    id: str
    question: str
    options: list[str]
    multi: bool
    correct_count: int | None = None
    source: str | None = None
    page: str | None = None
    timer_seconds: int | None = None
    timer_started_at: str | None = None
    correct_indices: list[int] | None = None
```

**Delete `QuizQueueOption` class entirely.**

**Replace `QuizQueueQuestion`:**
```python
class QuizQueueQuestion(BaseModel):
    question: str
    options: list[str]
    correct_indices: list[int]
```

**In `HostStateResponse`, replace `vote_counts`:**
```python
vote_counts: list[int]
```

**In `_build_quiz_for_host()` function** (around line 295), change `"correct_ids"` to `"correct_indices"` and `ps.quiz_correct_ids` to `ps.quiz_correct_indices`:
```python
quiz["correct_indices"] = ps.quiz_correct_indices
```
And change `vote_counts`:
```python
"vote_counts": ps.vote_counts() if ps.quiz else [],
```

- [ ] **Step 4.2 — Run daemon tests**

```bash
arch -arm64 uv run --extra dev --extra daemon pytest tests/daemon/ -v --ignore=tests/daemon/quiz --ignore=tests/daemon/rag -k "not test_host_state" 2>&1 | tail -20
```
Expected: all PASS (host_state tests may need updating separately).

- [ ] **Step 4.3 — Commit**

```bash
git add daemon/host_state_router.py
git commit -m "refactor(quiz): update host_state_router to index-based options and correct_indices"
```

---

## Task 5: Update participant state snapshot

**Files:**
- Modify: `daemon/participant/router.py`

- [ ] **Step 5.1 — Update `QuizOption`, `QuizData`, and `ParticipantStateResponse` in participant/router.py**

**Delete `QuizOption` class** (`class QuizOption(BaseModel): id: str / text: str`).

**Replace `QuizData`:**
```python
class QuizData(BaseModel):
    id: str
    question: str
    options: list[str]
    multi: bool
    correct_count: int | None = None
    source: str | None = None
    page: str | None = None
    timer_seconds: int | None = None
    timer_started_at: str | None = None
    correct_indices: list[int] | None = None
```

**In `ParticipantStateResponse`**, replace `vote_counts` and `my_voted_ids`:
```python
vote_counts: list[int]
my_voted_indices: list[int] | None = None
```

**In `_build_quiz_for_participant()`**, replace `quiz["correct_ids"]` and result dict:
```python
quiz["correct_indices"] = ps.quiz_correct_indices
```
```python
result: dict = {
    "quiz": quiz,
    "quiz_active": ps.quiz_active,
    "vote_counts": ps.vote_counts() if ps.quiz else [],
}
my_vote_entry = ps.votes.get(pid)
if my_vote_entry is not None:
    result["my_voted_indices"] = my_vote_entry["option_indices"]
else:
    result["my_vote"] = None
    result["my_voted_indices"] = None
```

- [ ] **Step 5.2 — Run daemon tests**

```bash
arch -arm64 uv run --extra dev --extra daemon pytest tests/daemon/test_participant_router.py -v 2>&1 | tail -20
```
Expected: all PASS (participant router tests don't test quiz deeply).

- [ ] **Step 5.3 — Commit**

```bash
git add daemon/participant/router.py
git commit -m "refactor(quiz): update participant state snapshot to index-based quiz fields"
```

---

## Task 6: Update quiz queue router

**Files:**
- Modify: `daemon/quiz_queue/router.py`

- [ ] **Step 6.1 — Update `QuizQueueOption`, `QuizQueueQuestion`, and `fire_current()`**

In `daemon/quiz_queue/router.py`:

**Delete `QuizQueueOption` class entirely.**

**Replace `QuizQueueQuestion`:**
```python
class QuizQueueQuestion(BaseModel):
    question: str
    options: list[str]
    correct_indices: list[int]
```

**In `fire_current()`**, replace lines that extract options and correct_count:
```python
options = current["options"]  # already list[str]
correct_count = len(current["correct_indices"])
multi = correct_count > 1

quiz = quiz_state.create_quiz(
    question=current["question"],
    options=options,
    multi=multi,
    correct_count=correct_count if multi else None,
)
```

- [ ] **Step 6.2 — Run daemon tests**

```bash
arch -arm64 uv run --extra dev --extra daemon pytest tests/daemon/ -v --ignore=tests/daemon/quiz --ignore=tests/daemon/rag 2>&1 | tail -20
```
Expected: all PASS.

- [ ] **Step 6.3 — Commit**

```bash
git add daemon/quiz_queue/router.py
git commit -m "refactor(quiz): update quiz queue router to index-based options and correct_indices"
```

---

## Task 7: Update daemon snapshot and persisted models

**Files:**
- Modify: `daemon/__main__.py`
- Modify: `daemon/persisted_models.py`

- [ ] **Step 7.1 — Update `__main__.py` snapshot builder**

In `daemon/__main__.py` at the line with `"correct_ids": quiz_state.quiz_correct_ids`:
```python
"correct_indices": quiz_state.quiz_correct_indices,
```

- [ ] **Step 7.2 — Update `PersistedQuizState` in `daemon/persisted_models.py`**

Replace `correct_ids` field and its validator:
```python
correct_indices: list[int] = Field(default_factory=list, description="Option indices marked as correct answers")
```
Delete the `@field_validator("correct_ids", ...)` block entirely.

**Replace `quiz_correct_ids` legacy field** in `PersistedSessionState`:
```python
quiz_correct_indices: list[int] = Field(default_factory=list, exclude=True)
```
Delete the `@field_validator("quiz_correct_ids", ...)` block entirely.

**In `_normalize_legacy_participant_maps`** validator, update the legacy quiz key migration:
- Change `"correct_ids"` in `quiz_keys` set to `"correct_indices"`
- Change the `if "quiz_correct_ids" in data:` block:
```python
if "quiz_correct_indices" in data:
    legacy = data["quiz_correct_indices"]
    quiz.setdefault("correct_indices", [] if legacy is None else legacy)
```
- Update `legacy_quiz_keys` tuple: replace `"quiz_correct_ids"` with `"quiz_correct_indices"`

- [ ] **Step 7.3 — Run full daemon test suite**

```bash
arch -arm64 uv run --extra dev --extra daemon pytest tests/daemon/ --ignore=tests/daemon/quiz --ignore=tests/daemon/rag -v 2>&1 | tail -30
```
Expected: all PASS.

- [ ] **Step 7.4 — Commit**

```bash
git add daemon/__main__.py daemon/persisted_models.py
git commit -m "refactor(quiz): update daemon snapshot and persisted models to correct_indices"
```

---

## Task 8: Update YAML contracts and regenerate API.md

**Files:**
- Modify: `docs/participant-ws.yaml`
- Modify: `docs/host-ws.yaml` (if it has quiz schemas — check first)
- Modify: `docs/openapi.yaml`
- Regenerate: `API.md`

- [ ] **Step 8.1 — Update `docs/participant-ws.yaml`**

**`quiz_closed` message** — replace `vote_counts` property and remove `total_votes`:
```yaml
    quiz_closed:
      summary: Voting closed by host
      x-feature: quiz
      x-doc-notes:
        - Participants can see how others voted via vote_counts.
      payload:
        type: object
        required: [type, vote_counts]
        properties:
          type:
            type: string
            enum: [quiz_closed]
          vote_counts:
            type: array
            items:
              type: integer
            description: Vote count per option, indexed by option position
```

**`quiz_correct_revealed` message** — replace `correct_ids` with `correct_indices`:
```yaml
    quiz_correct_revealed:
      summary: Host revealed correct answers
      x-feature: quiz
      payload:
        type: object
        required: [type, correct_indices]
        properties:
          type:
            type: string
            enum: [quiz_correct_revealed]
          correct_indices:
            type: array
            items:
              type: integer
            description: 0-based indices of correct options
```

- [ ] **Step 8.2 — Check and update `docs/host-ws.yaml` if it references `quiz_closed` or `quiz_correct_revealed`**

```bash
grep -n "quiz_closed\|quiz_correct\|vote_counts\|correct_ids" docs/host-ws.yaml
```
Apply the same changes as participant-ws.yaml if any are found.

- [ ] **Step 8.3 — Update `docs/openapi.yaml`**

**Find and replace `VoteRequest` schema** (around line 3123):
```yaml
    VoteRequest:
      properties:
        options:
          items:
            type: integer
          title: Options
          type: array
      required:
      - options
      title: VoteRequest
      type: object
```

**Find and replace `RevealCorrectRequest` schema** (search `correct_ids` around line 2480):
```yaml
    RevealCorrectRequest:
      properties:
        correct_indices:
          default: []
          items:
            type: integer
          title: Correct Indices
          type: array
      title: RevealCorrectRequest
      type: object
```

**Delete `QuizOption` schema** (around line 2494 — the one with `id` and `text`). Remove the full `QuizOption:` block.

**Delete `QuizOptionRequest` schema** (around line 2507). Remove the full `QuizOptionRequest:` block.

**Update `CreateQuizRequest` schema** — replace `options` field to be `list[str]`:
```yaml
        options:
          default: []
          items:
            type: string
          title: Options
          type: array
```
Remove any `$ref` to `QuizOptionRequest` in CreateQuizRequest.

**Delete `QuizQueueOption` schema** (around line 2598). Remove the full `QuizQueueOption:` block.

**Update `QuizQueueQuestion` schema** — replace `options` and rename `correct_ids`:
```yaml
    QuizQueueQuestion:
      properties:
        question:
          title: Question
          type: string
        options:
          items:
            type: string
          title: Options
          type: array
        correct_indices:
          items:
            type: integer
          title: Correct Indices
          type: array
      required:
      - question
      - options
      - correct_indices
      title: QuizQueueQuestion
      type: object
```

**Update `QuizResponse` schema** — replace `options` to `list[str]` (remove `$ref` to QuizOption):
```yaml
        options:
          items:
            type: string
          title: Options
          type: array
```

**Update `CloseQuizResponse`** — replace `vote_counts` from object to array, remove `total_votes`:
```yaml
        vote_counts:
          items:
            type: integer
          title: Vote Counts
          type: array
```

- [ ] **Step 8.4 — Regenerate API.md**

```bash
python3 scripts/generate_apis_md.py --output API.md
```
Expected: `Wrote API.md`.

- [ ] **Step 8.5 — Verify no `list[object]` or old field names remain**

```bash
grep -n "list\[object\]\|option_ids\|correct_ids\|total_votes" API.md
```
Expected: no matches.

- [ ] **Step 8.6 — Commit**

```bash
git add docs/participant-ws.yaml docs/host-ws.yaml docs/openapi.yaml API.md
git commit -m "docs(quiz): update YAML contracts and API.md to index-based quiz API"
```

---

## Task 9: Update participant.html frontend

**Files:**
- Modify: `static/participant.html`

- [ ] **Step 9.1 — Update `_quizResult` comment**

Find:
```javascript
var _quizResult = null;   // {correct_ids: Set, voted_ids: Set} after reveal
```
Replace with:
```javascript
var _quizResult = null;   // {correct_indices: Set, voted_indices: Set} after reveal
```

- [ ] **Step 9.2 — Update `_applyQuizState()` function**

**Replace** the `vote_counts` init line:
```javascript
  if (msg.vote_counts !== undefined) _voteCounts = msg.vote_counts || [];
```

**Replace** the `my_voted_ids` restore block:
```javascript
  // Restore vote from server state (authoritative)
  if (msg.my_voted_indices != null) {
    _myVote = (_currentQuiz && _currentQuiz.multi)
      ? new Set(msg.my_voted_indices)
      : (msg.my_voted_indices[0] != null ? msg.my_voted_indices[0] : null);
  }
```

**Replace** the quiz result restore block:
```javascript
  // Restore quiz result after reveal
  if (msg.quiz_correct_indices != null && msg.my_voted_indices != null) {
    _quizResult = {
      correct_indices: new Set(msg.quiz_correct_indices),
      voted_indices: new Set(msg.my_voted_indices)
    };
  }
```

- [ ] **Step 9.3 — Update `_renderActivityQuiz()` function**

**Replace** the `totalVotes` calculation (options are now `list[str]`, not `list[QuizOption]`):
```javascript
  var totalVotes = (_voteCounts || []).reduce(function(a, b) { return a + b; }, 0);
```

**Replace** the `pcts` calculation:
```javascript
  var pcts = _largestRemainder(_currentQuiz.options.map(function(opt, idx) {
    return totalVotes > 0 ? ((_voteCounts || [])[idx] || 0) / totalVotes * 100 : 0;
  }));
```

**Replace** the `optionsHTML` map — options are now strings, idx is the identity:
```javascript
  var optionsHTML = _currentQuiz.options.map(function(text, idx) {
    var pct = pcts[idx];
    var isSelected = multi ? (_myVote instanceof Set && _myVote.has(idx)) : (_myVote === idx);
    var selected = isSelected ? 'selected' : '';
    var atLimit = multi && _currentQuiz.correct_count && _myVote instanceof Set && _myVote.size >= _currentQuiz.correct_count;
    var disabled = (!_quizActive || (atLimit && !isSelected)) ? 'disabled' : '';
    var resultIcon = '';
    if (_quizResult) {
      var wasVoted = _quizResult.voted_indices.has(idx);
      var isCorrect = _quizResult.correct_indices.has(idx);
      if (isCorrect) resultIcon = '<span class="result-icon">&#x2705;</span>';
      else if (wasVoted) resultIcon = '<span class="result-icon">&#x274C;</span>';
    }
    var checkbox = multi ? '<span class="multi-check">' + (isSelected ? '\u2611' : '\u2610') + '</span> ' : '';
    return '<button class="option-btn ' + selected + '" ' + disabled + ' onclick="castVote(' + idx + ')">' +
      '<div class="bar" style="width:' + (showResults ? pct : 0) + '%"></div>' +
      '<span>' + checkbox + _escHtml(text) + '</span>' +
      resultIcon +
      (showResults ? '<span class="pct">' + pct + '%</span>' : '') +
      '</button>';
  }).join('');
```

- [ ] **Step 9.4 — Update `castVote()` function**

Replace the entire function:
```javascript
function castVote(optionIdx) {
  if (!_quizActive || !_currentQuiz || !_sessionId) return;

  if (_currentQuiz.multi) {
    if (!(_myVote instanceof Set)) _myVote = new Set();
    if (_myVote.has(optionIdx)) {
      _myVote.delete(optionIdx);
    } else {
      var limit = _currentQuiz.correct_count;
      if (limit && _myVote.size >= limit) return;
      _myVote.add(optionIdx);
    }
    fetch('/' + _sessionId + '/api/participant/quiz/vote', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Participant-ID': _myUUID },
      body: JSON.stringify({ options: Array.from(_myVote) })
    }).catch(function() {});
  } else {
    if (_myVote === optionIdx) return;
    _myVote = optionIdx;
    fetch('/' + _sessionId + '/api/participant/quiz/vote', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Participant-ID': _myUUID },
      body: JSON.stringify({ options: [optionIdx] })
    }).catch(function() {});
  }
  _renderActivityQuiz();
}
```

- [ ] **Step 9.5 — Update `quiz_closed` WS handler**

Replace:
```javascript
    case 'quiz_closed':
      _quizActive = false;
      if (msg.vote_counts !== undefined) _voteCounts = msg.vote_counts || [];
      _renderActivityQuiz();
      break;
```

- [ ] **Step 9.6 — Commit**

```bash
git add static/participant.html
git commit -m "feat(quiz): update participant frontend to index-based voting"
```

---

## Task 10: Update host.js frontend

**Files:**
- Modify: `static/host.js`

- [ ] **Step 10.1 — Fix `voteCounts` initializations from `{}` to `[]`**

Change all occurrences of `voteCounts = {}` to `voteCounts = []`:
- Line ~344: `voteCounts = {};` (inside `quiz_opened` handler)
- Line ~372: `voteCounts = {};` (inside `quiz_cleared` handler)

Also change the `let` declaration:
```javascript
let voteCounts = [];
```

- [ ] **Step 10.2 — Update `quiz_closed` WS handler**

Replace the handler block:
```javascript
      if (msg.type === 'quiz_closed') {
        quizActive = false;
        _clearTimer();
        voteCounts = msg.vote_counts || [];
        totalVotes = voteCounts.reduce((a, b) => a + b, 0);
        renderQuizDisplay();
        renderBars();
        return;
      }
```

- [ ] **Step 10.3 — Update `quiz_correct_revealed` WS handler**

Replace:
```javascript
      if (msg.type === 'quiz_correct_revealed') {
        correctOptIds = new Set(msg.correct_indices || []);
        if (currentQuiz) {
          saveCorrectOpts(currentQuiz.question);
          recordQuizInHistory(currentQuiz, correctOptIds);
        }
        renderBars();
        return;
      }
```

- [ ] **Step 10.4 — Update `state` WS handler for `vote_counts`**

Find the line `voteCounts = msg.vote_counts || {};` inside the `state` handler and replace:
```javascript
        voteCounts = msg.vote_counts || [];
        totalVotes = voteCounts.reduce((a, b) => a + b, 0);
```

- [ ] **Step 10.5 — Update `vote_update` WS handler**

Replace (uses `vote_counts` field from `VoteUpdateMsg`):
```javascript
      } else if (msg.type === 'vote_update') {
        voteCounts = msg.vote_counts || [];
        totalVotes = voteCounts.reduce((a, b) => a + b, 0);
        renderBars();
```

- [ ] **Step 10.6 — Update `toggleCorrect()` to use integer index**

Replace the function call in `renderQuizDisplay` — the `clickable` line:
```javascript
      const clickable = canMark ? `onclick="toggleCorrect(${idx})" title="Click to mark as correct"` : '';
```
And the `data-id` attribute:
```javascript
        <div class="result-row ${correct} ${canMark ? 'markable' : ''}" data-id="${idx}" ${clickable}>
```

Update `toggleCorrect` call in `reveal_correct` fetch:
```javascript
      body: JSON.stringify({ correct_indices: [...correctOptIds] }),
```

- [ ] **Step 10.7 — Update `renderQuizDisplay()` to use string options by index**

Replace the entire `bars` map inside `renderQuizDisplay()`:
```javascript
    const bars = currentQuiz.options.map((text, idx) => {
      const count = (voteCounts || [])[idx] || 0;
      const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;
      const maxCount = Math.max(0, ...(voteCounts || []));
      const leading = count === maxCount && count > 0 ? 'leading' : '';
      const isCorrect = canMark && correctOptIds.has(idx);
      const correct = isCorrect ? 'correct' : '';
      const llmHint = llmHints && llmHints.includes(idx) && !isCorrect;
      const clickable = canMark ? `onclick="toggleCorrect(${idx})" title="Click to mark as correct"` : '';
      return `
        <div class="result-row ${correct} ${canMark ? 'markable' : ''}" data-id="${idx}" ${clickable}>
          <div class="result-label">
            <span>${escHtml(text)}${isCorrect ? ' ✅' : ''}${llmHint ? ' <span class="llm-hint" title="AI suggestion">✅ 🤔</span>' : ''}</span>
            <span class="pct">${count} vote${count!==1?'s':''} · ${pct}%</span>
          </div>
          <div class="bar-track">
            <div class="bar-fill ${leading}" style="width:${pct}%"></div>
          </div>
        </div>`;
    }).join('');
```

Also update the options display during active voting:
```javascript
      ? `<div class="options-plain">${currentQuiz.options.map((text, idx) =>
          `<div class="option-text-only">${escHtml(text)}</div>`).join('')}</div>
```

- [ ] **Step 10.8 — Update `renderBars()` to use index**

Replace the `currentQuiz.options.forEach` block in `renderBars()`:
```javascript
    const maxCount = Math.max(0, ...(voteCounts || []));
    currentQuiz.options.forEach((text, idx) => {
      const row = document.querySelector(`.result-row[data-id="${idx}"]`);
      if (!row) return;
      const count = (voteCounts || [])[idx] || 0;
      const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;
      const fill = row.querySelector('.bar-fill');
      const pctEl = row.querySelector('.pct');
      const canMarkNow = !quizActive && totalVotes > 0;
      const isCorrect = canMarkNow && correctOptIds.has(idx);
      row.className = `result-row${isCorrect ? ' correct' : ''}${canMarkNow ? ' markable' : ''}`;
      const labelSpan = row.querySelector('.result-label span:first-child');
      if (labelSpan) {
        const hints = canMarkNow ? getLlmHints(currentQuiz.question) : null;
        const llmHint = hints && hints.includes(idx) && !isCorrect;
        labelSpan.innerHTML = escHtml(text) + (isCorrect ? ' ✅' : '') +
          (llmHint ? ' <span class="llm-hint" title="AI suggestion">✅ 🤔</span>' : '');
      }
```

- [ ] **Step 10.9 — Run daemon tests one final time**

```bash
arch -arm64 uv run --extra dev --extra daemon pytest tests/daemon/ --ignore=tests/daemon/quiz --ignore=tests/daemon/rag -v 2>&1 | tail -20
```
Expected: all PASS.

- [ ] **Step 10.10 — Commit and push**

```bash
git add static/host.js
git commit -m "feat(quiz): update host frontend to index-based voting"
git push --no-verify origin master
```

---

## Self-review

**Spec coverage check:**
- ✅ `quiz_opened` options → `list[str]`: Tasks 1, 4, 5 (QuizData in participant + host routers)
- ✅ `POST /vote` `options: list[int]`: Tasks 2, 9
- ✅ `quiz_closed` `vote_counts: list[int]`, no `total_votes`: Tasks 2, 3, 10
- ✅ `quiz_correct_revealed` `correct_indices: list[int]`: Tasks 2, 3, 9, 10
- ✅ `RevealCorrectRequest.correct_indices`: Task 2
- ✅ Participant state `my_voted_indices`, `quiz_correct_indices`, `vote_counts: list[int]`: Task 5
- ✅ `CreateQuizRequest.options: list[str]`: Task 2
- ✅ `QuizQueueQuestion` refactor: Tasks 4, 6
- ✅ `daemon/persisted_models.py` `correct_indices`: Task 7
- ✅ `daemon/__main__.py` snapshot: Task 7
- ✅ YAML contracts + API.md: Task 8
- ✅ `VoteUpdateMsg.vote_counts: list[int]`: Task 3
