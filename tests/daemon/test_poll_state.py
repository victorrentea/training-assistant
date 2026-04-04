"""Tests for daemon/poll/state.py — PollState singleton."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from daemon.poll.state import PollState, _MAX_POINTS, _MIN_POINTS, _SLOWEST_MULTIPLIER


class MockScores:
    def __init__(self):
        self.scores = {}

    def add_score(self, pid, pts):
        self.scores[pid] = self.scores.get(pid, 0) + pts

    def snapshot(self):
        return dict(self.scores)


def _make_poll(ps, multi=False, correct_count=None):
    options = [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}, {"id": "c", "text": "C"}]
    ps.create_poll("Test?", options, multi=multi, correct_count=correct_count)
    ps.open_poll(lambda: None)  # no-op scores snapshot


# ── create_poll ──────────────────────────────────────────────────────────────

def test_create_poll():
    ps = PollState()
    _make_poll(ps)
    # After open_poll votes are cleared
    assert ps.poll is not None
    assert ps.poll["question"] == "Test?"
    assert len(ps.poll["options"]) == 3
    assert ps.poll_active is True
    assert ps.votes == {}
    assert ps.poll_correct_ids is None


def test_create_poll_clears_previous_state():
    ps = PollState()
    _make_poll(ps)
    ps.cast_vote("pid1", option_id="a")
    # Create a new poll — should clear votes
    result = ps.create_poll("New?", [{"id": "x", "text": "X"}])
    assert ps.votes == {}
    assert ps.poll_active is False
    assert result["question"] == "New?"


def test_create_poll_with_correct_count_zero():
    """correct_count=0 must be stored — not filtered by 'if correct_count:'"""
    ps = PollState()
    options = [{"id": "a", "text": "A"}]
    ps.create_poll("Q?", options, correct_count=0)
    assert "correct_count" in ps.poll
    assert ps.poll["correct_count"] == 0


# ── open_poll ────────────────────────────────────────────────────────────────

def test_open_poll():
    ps = PollState()
    options = [{"id": "a", "text": "A"}]
    ps.create_poll("Q?", options)
    # Pre-seed some votes to verify they're cleared
    ps.votes["old"] = "a"
    snapshot_called = []
    ps.open_poll(lambda: snapshot_called.append(True))
    assert ps.poll_active is True
    assert ps.votes == {}
    assert ps.poll_opened_at is not None
    assert snapshot_called == [True]


# ── close_poll ───────────────────────────────────────────────────────────────

def test_close_poll():
    ps = PollState()
    _make_poll(ps)
    ps.cast_vote("pid1", option_id="a")
    ps.cast_vote("pid2", option_id="b")
    result = ps.close_poll()
    assert ps.poll_active is False
    assert result["total_votes"] == 2
    assert result["vote_counts"] == {"a": 1, "b": 1}


# ── cast_vote single-select ──────────────────────────────────────────────────

def test_cast_vote_single_select():
    ps = PollState()
    _make_poll(ps)
    result = ps.cast_vote("pid1", option_id="a")
    assert result is True
    assert ps.votes["pid1"] == "a"
    assert "pid1" in ps.vote_times


def test_cast_vote_single_select_final():
    """Second vote from same pid must be rejected."""
    ps = PollState()
    _make_poll(ps)
    ps.cast_vote("pid1", option_id="a")
    result = ps.cast_vote("pid1", option_id="b")
    assert result is False
    assert ps.votes["pid1"] == "a"  # original vote unchanged


# ── cast_vote multi-select ───────────────────────────────────────────────────

def test_cast_vote_multi_select():
    ps = PollState()
    _make_poll(ps, multi=True, correct_count=2)
    result = ps.cast_vote("pid1", option_ids=["a", "b"])
    assert result is True
    assert ps.votes["pid1"] == ["a", "b"]


def test_cast_vote_multi_select_toggle():
    """Multi-select allows overwriting the selection set."""
    ps = PollState()
    _make_poll(ps, multi=True, correct_count=2)
    ps.cast_vote("pid1", option_ids=["a", "b"])
    result = ps.cast_vote("pid1", option_ids=["b", "c"])
    assert result is True
    assert ps.votes["pid1"] == ["b", "c"]


def test_cast_vote_multi_select_over_limit():
    """Reject if more options selected than correct_count."""
    ps = PollState()
    _make_poll(ps, multi=True, correct_count=2)
    result = ps.cast_vote("pid1", option_ids=["a", "b", "c"])
    assert result is False


# ── cast_vote error cases ────────────────────────────────────────────────────

def test_cast_vote_poll_closed():
    ps = PollState()
    _make_poll(ps)
    ps.close_poll()
    result = ps.cast_vote("pid1", option_id="a")
    assert result is False


def test_cast_vote_no_poll():
    ps = PollState()
    result = ps.cast_vote("pid1", option_id="a")
    assert result is False


def test_cast_vote_invalid_option():
    ps = PollState()
    _make_poll(ps)
    result = ps.cast_vote("pid1", option_id="z")
    assert result is False


# ── reveal_correct ───────────────────────────────────────────────────────────

def test_reveal_correct_speed_scoring():
    """Fastest voter gets ~1000pts, slower voter gets less."""
    ps = PollState()
    _make_poll(ps)

    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    opened_at = base_time
    fast_vote_time = base_time + timedelta(seconds=2)
    slow_vote_time = base_time + timedelta(seconds=8)

    ps.poll_opened_at = opened_at
    ps.votes = {"fast": "a", "slow": "a"}
    ps.vote_times = {"fast": fast_vote_time, "slow": slow_vote_time}

    scores = MockScores()
    result = ps.reveal_correct(["a"], scores)

    assert "fast" in scores.scores
    assert "slow" in scores.scores
    assert scores.scores["fast"] > scores.scores["slow"]
    assert scores.scores["fast"] == _MAX_POINTS  # fastest gets max


def test_reveal_correct_multi_proportional():
    """Voter selects 2 of 3 correct + 1 wrong → ratio = (2-1)/3 ≈ 0.333"""
    ps = PollState()
    options = [
        {"id": "a", "text": "A"}, {"id": "b", "text": "B"},
        {"id": "c", "text": "C"}, {"id": "d", "text": "D"},
    ]
    ps.create_poll("Q?", options, multi=True, correct_count=3)
    ps.open_poll(lambda: None)

    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ps.poll_opened_at = base_time
    # Selects a, b (correct), d (wrong) — misses c
    ps.votes = {"pid1": ["a", "b", "d"]}
    ps.vote_times = {"pid1": base_time + timedelta(seconds=1)}

    scores = MockScores()
    ps.reveal_correct(["a", "b", "c"], scores)

    # ratio = (2-1)/3 = 0.333...
    assert "pid1" in scores.scores
    expected_ratio = (2 - 1) / 3
    expected_pts = round(_MAX_POINTS * expected_ratio)
    assert scores.scores["pid1"] == expected_pts


def test_reveal_correct_no_votes():
    """No votes → no scores awarded, no error."""
    ps = PollState()
    _make_poll(ps)
    scores = MockScores()
    result = ps.reveal_correct(["a"], scores)
    assert scores.scores == {}
    assert result["correct_ids"] == ["a"]


# ── start_timer ───────────────────────────────────────────────────────────────

def test_start_timer():
    ps = PollState()
    result = ps.start_timer(30)
    assert result["seconds"] == 30
    assert "started_at" in result
    assert ps.poll_timer_seconds == 30
    assert ps.poll_timer_started_at is not None
    # Verify ISO format
    datetime.fromisoformat(result["started_at"])


# ── clear ─────────────────────────────────────────────────────────────────────

def test_clear():
    ps = PollState()
    _make_poll(ps)
    ps.cast_vote("pid1", option_id="a")
    ps.start_timer(20)
    ps.clear()
    assert ps.poll is None
    assert ps.poll_active is False
    assert ps.votes == {}
    assert ps.vote_times == {}
    assert ps.poll_opened_at is None
    assert ps.poll_correct_ids is None
    assert ps.poll_timer_seconds is None
    assert ps.poll_timer_started_at is None


# ── vote_counts dirty flag ────────────────────────────────────────────────────

def test_vote_counts_dirty_flag():
    ps = PollState()
    _make_poll(ps)
    ps.cast_vote("pid1", option_id="a")
    # First call computes and caches
    counts1 = ps.vote_counts()
    assert counts1 == {"a": 1}
    assert ps._vote_counts_dirty is False

    # Second call uses cache (no change)
    counts2 = ps.vote_counts()
    assert counts2 is counts1  # same object from cache

    # New vote invalidates cache
    ps.cast_vote("pid2", option_id="b")
    assert ps._vote_counts_dirty is True
    counts3 = ps.vote_counts()
    assert counts3 == {"a": 1, "b": 1}
    assert ps._vote_counts_dirty is False


# ── quiz_md ───────────────────────────────────────────────────────────────────

def test_append_to_quiz_md():
    ps = PollState()
    _make_poll(ps)
    ps.cast_vote("pid1", option_id="a")
    ps.reveal_correct(["a"], MockScores())

    md = ps.quiz_md_content
    assert "### Test?" in md
    assert "- [✓] A" in md
    assert "- [✗] B" in md
    assert "- [✗] C" in md
