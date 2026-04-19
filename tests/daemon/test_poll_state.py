"""Tests for daemon/poll/state.py — PollState singleton."""
import pytest
from datetime import datetime, timezone, timedelta

from daemon.poll.state import PollState, _MAX_POINTS, _MIN_POINTS, _SLOWEST_MULTIPLIER


class MockScores:
    def __init__(self):
        self.scores = {}

    def add_score(self, pid, pts):
        self.scores[pid] = self.scores.get(pid, 0) + pts

    def snapshot(self):
        return dict(self.scores)


def _make_poll(ps, multi=False, correct_count=None):
    ps.create_poll("Test?", ["A", "B", "C"], multi=multi, correct_count=correct_count)
    ps.open_poll(lambda: None)


def test_create_poll():
    ps = PollState()
    _make_poll(ps)
    assert ps.poll is not None
    assert ps.poll["question"] == "Test?"
    assert ps.poll["options"] == ["A", "B", "C"]
    assert ps.poll_active is True
    assert ps.votes == {}
    assert ps.poll_correct_indices is None


def test_create_poll_clears_previous_state():
    ps = PollState()
    _make_poll(ps)
    ps.cast_vote("pid1", option_indices=[0])
    result = ps.create_poll("New?", ["X"])
    assert ps.votes == {}
    assert ps.poll_active is False
    assert result["question"] == "New?"


def test_create_poll_with_correct_count_zero():
    """correct_count=0 must be stored — not filtered by 'if correct_count:'"""
    ps = PollState()
    ps.create_poll("Q?", ["A"], correct_count=0)
    assert "correct_count" in ps.poll
    assert ps.poll["correct_count"] == 0


def test_open_poll():
    ps = PollState()
    ps.create_poll("Q?", ["A"])
    ps.votes["old"] = {"option_indices": [0], "voted_at": "2024-01-01T00:00:00+00:00"}
    snapshot_called = []
    ps.open_poll(lambda: snapshot_called.append(True))
    assert ps.poll_active is True
    assert ps.votes == {}
    assert ps.poll_opened_at is not None
    assert snapshot_called == [True]


def test_close_poll():
    ps = PollState()
    _make_poll(ps)
    ps.cast_vote("pid1", option_indices=[0])
    ps.cast_vote("pid2", option_indices=[1])
    result = ps.close_poll()
    assert ps.poll_active is False
    assert result["vote_counts"] == [1, 1, 0]
    assert "total_votes" not in result


def test_cast_vote_single_select():
    ps = PollState()
    _make_poll(ps)
    result = ps.cast_vote("pid1", option_indices=[0])
    assert result is True
    assert ps.votes["pid1"]["option_indices"] == [0]
    assert "voted_at" in ps.votes["pid1"]


def test_cast_vote_single_select_final():
    """Second vote from same pid must be rejected."""
    ps = PollState()
    _make_poll(ps)
    ps.cast_vote("pid1", option_indices=[0])
    result = ps.cast_vote("pid1", option_indices=[1])
    assert result is False
    assert ps.votes["pid1"]["option_indices"] == [0]


def test_cast_vote_multi_select():
    ps = PollState()
    _make_poll(ps, multi=True, correct_count=2)
    result = ps.cast_vote("pid1", option_indices=[0, 1])
    assert result is True
    assert ps.votes["pid1"]["option_indices"] == [0, 1]


def test_cast_vote_multi_select_toggle():
    """Multi-select votes are final — second attempt rejected."""
    ps = PollState()
    _make_poll(ps, multi=True, correct_count=2)
    ps.cast_vote("pid1", option_indices=[0, 1])
    result = ps.cast_vote("pid1", option_indices=[1, 2])
    assert result is False
    assert ps.votes["pid1"]["option_indices"] == [0, 1]


def test_cast_vote_multi_select_over_limit():
    ps = PollState()
    _make_poll(ps, multi=True, correct_count=2)
    result = ps.cast_vote("pid1", option_indices=[0, 1, 2])
    assert result is False


def test_cast_vote_poll_closed():
    ps = PollState()
    _make_poll(ps)
    ps.close_poll()
    result = ps.cast_vote("pid1", option_indices=[0])
    assert result is False


def test_cast_vote_no_poll():
    ps = PollState()
    result = ps.cast_vote("pid1", option_indices=[0])
    assert result is False


def test_cast_vote_invalid_option():
    ps = PollState()
    _make_poll(ps)
    result = ps.cast_vote("pid1", option_indices=[99])
    assert result is False


def test_reveal_correct_speed_scoring():
    """Fastest voter gets ~1000pts, slower voter gets less."""
    ps = PollState()
    _make_poll(ps)
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ps.poll_opened_at = base_time
    ps.votes = {
        "fast": {"option_indices": [0], "voted_at": (base_time + timedelta(seconds=2)).isoformat()},
        "slow": {"option_indices": [0], "voted_at": (base_time + timedelta(seconds=8)).isoformat()},
    }
    scores = MockScores()
    result = ps.reveal_correct([0], scores)
    assert scores.scores["fast"] > scores.scores["slow"]
    assert scores.scores["fast"] == _MAX_POINTS


def test_reveal_correct_multi_proportional():
    """Voter selects 2 of 3 correct + 1 wrong → ratio = (2-1)/3"""
    ps = PollState()
    ps.create_poll("Q?", ["A", "B", "C", "D"], multi=True, correct_count=3)
    ps.open_poll(lambda: None)
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ps.poll_opened_at = base_time
    vote_time = (base_time + timedelta(seconds=1)).isoformat()
    ps.votes = {"pid1": {"option_indices": [0, 1, 3], "voted_at": vote_time}}
    scores = MockScores()
    ps.reveal_correct([0, 1, 2], scores)
    assert "pid1" in scores.scores
    expected_ratio = (2 - 1) / 3
    expected_pts = round(_MAX_POINTS * expected_ratio)
    assert scores.scores["pid1"] == expected_pts


def test_reveal_correct_no_votes():
    ps = PollState()
    _make_poll(ps)
    scores = MockScores()
    result = ps.reveal_correct([0], scores)
    assert scores.scores == {}
    assert result["correct_indices"] == [0]


def test_start_timer():
    ps = PollState()
    result = ps.start_timer(30)
    assert result["seconds"] == 30
    assert "started_at" in result
    assert ps.poll_timer_seconds == 30
    datetime.fromisoformat(result["started_at"])


def test_clear():
    ps = PollState()
    _make_poll(ps)
    ps.cast_vote("pid1", option_indices=[0])
    ps.start_timer(20)
    ps.clear()
    assert ps.poll is None
    assert ps.poll_active is False
    assert ps.votes == {}
    assert ps.poll_opened_at is None
    assert ps.poll_correct_indices is None
    assert ps.poll_timer_seconds is None
    assert ps.poll_timer_started_at is None


def test_vote_counts_returns_list():
    ps = PollState()
    _make_poll(ps)
    ps.cast_vote("pid1", option_indices=[0])
    ps.cast_vote("pid2", option_indices=[1])
    counts = ps.vote_counts()
    assert counts == [1, 1, 0]


def test_vote_counts_dirty_flag():
    ps = PollState()
    _make_poll(ps)
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


def test_append_to_poll_md():
    ps = PollState()
    _make_poll(ps)
    ps.cast_vote("pid1", option_indices=[0])
    ps.reveal_correct([0], MockScores())
    md = ps.poll_md_content
    assert "### Test?" in md
    assert "- [✓] A" in md
    assert "- [✗] B" in md
    assert "- [✗] C" in md
