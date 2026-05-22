"""Tests for daemon/quiz/state.py — QuizState singleton."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from daemon.quiz.state import _MAX_POINTS, QuizState


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


def test_close_quiz():
    ps = QuizState()
    _make_quiz(ps)
    ps.cast_vote("pid1", option_indices=[0])
    ps.cast_vote("pid2", option_indices=[1])
    result = ps.close_quiz()
    assert ps.quiz_active is False
    assert result["vote_counts"] == [1, 1, 0]
    assert "total_votes" not in result


def test_cast_vote_single_select():
    ps = QuizState()
    _make_quiz(ps)
    result = ps.cast_vote("pid1", option_indices=[0])
    assert result is True
    assert ps.votes["pid1"]["option_indices"] == [0]
    assert "voted_at" in ps.votes["pid1"]


def test_cast_vote_single_select_overwrites():
    """Per CLAUDE.md, votes are mutable: a second vote from the same pid replaces the first."""
    ps = QuizState()
    _make_quiz(ps)
    ps.cast_vote("pid1", option_indices=[0])
    result = ps.cast_vote("pid1", option_indices=[1])
    assert result is True
    assert ps.votes["pid1"]["option_indices"] == [1]


def test_cast_vote_multi_select():
    ps = QuizState()
    _make_quiz(ps, multi=True, correct_count=2)
    result = ps.cast_vote("pid1", option_indices=[0, 1])
    assert result is True
    assert ps.votes["pid1"]["option_indices"] == [0, 1]


def test_cast_vote_multi_select_overwrites():
    """Multi-select participants toggle checkboxes — each click resends the full set,
    so subsequent votes must replace the previous selection."""
    ps = QuizState()
    _make_quiz(ps, multi=True, correct_count=2)
    ps.cast_vote("pid1", option_indices=[0, 1])
    result = ps.cast_vote("pid1", option_indices=[1, 2])
    assert result is True
    assert ps.votes["pid1"]["option_indices"] == [1, 2]


def test_cast_vote_multi_select_over_limit():
    ps = QuizState()
    _make_quiz(ps, multi=True, correct_count=2)
    result = ps.cast_vote("pid1", option_indices=[0, 1, 2])
    assert result is False


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
    ps.reveal_correct([0], scores)
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
    ps.votes = {"pid1": {"option_indices": [0, 1, 3], "voted_at": vote_time}}
    scores = MockScores()
    ps.reveal_correct([0, 1, 2], scores)
    assert "pid1" in scores.scores
    expected_ratio = (2 - 1) / 3
    expected_pts = round(_MAX_POINTS * expected_ratio)
    assert scores.scores["pid1"] == expected_pts


def test_reveal_correct_no_votes():
    ps = QuizState()
    _make_quiz(ps)
    scores = MockScores()
    result = ps.reveal_correct([0], scores)
    assert scores.scores == {}
    assert result["correct_indices"] == [0]


def test_start_timer():
    ps = QuizState()
    result = ps.start_timer(30)
    assert result["seconds"] == 30
    assert "started_at" in result
    assert ps.quiz_timer_seconds == 30
    datetime.fromisoformat(result["started_at"])


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


def test_awarded_points_initialized_empty():
    ps = QuizState()
    assert ps.awarded_points == {}


def test_awarded_points_reset_by_create_quiz():
    ps = QuizState()
    ps.awarded_points = {"alice": 1000, "bob": 500}
    ps.create_quiz("Q?", ["A", "B"])
    assert ps.awarded_points == {}


def test_awarded_points_reset_by_clear():
    ps = QuizState()
    ps.awarded_points = {"alice": 1000}
    ps.clear()
    assert ps.awarded_points == {}


def test_reveal_correct_twice_single_select_moves_points():
    """Second reveal with a different option must zero the first voter and award the new one."""
    ps = QuizState()
    ps.create_quiz("Q?", ["A", "B", "C"])
    ps.open_quiz(lambda: None)
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ps.quiz_opened_at = base_time
    vote_time = (base_time + timedelta(seconds=1)).isoformat()
    ps.votes = {
        "alice": {"option_indices": [0], "voted_at": vote_time},   # voted A
        "bob":   {"option_indices": [1], "voted_at": vote_time},   # voted B
    }
    scores = MockScores()

    # First reveal: A is correct → Alice gets 1000, Bob gets 0.
    ps.reveal_correct([0], scores)
    assert scores.scores.get("alice") == _MAX_POINTS
    assert scores.scores.get("bob", 0) == 0
    assert ps.awarded_points == {"alice": _MAX_POINTS}

    # Second reveal: B is correct → Alice goes back to 0, Bob gets 1000.
    ps.reveal_correct([1], scores)
    assert scores.scores.get("alice", 0) == 0
    assert scores.scores.get("bob") == _MAX_POINTS
    assert ps.awarded_points == {"bob": _MAX_POINTS}


def test_reveal_correct_twice_multi_select_partial_credit():
    """In multi-select quizzes, the partial-credit amount is what gets reversed."""
    ps = QuizState()
    ps.create_quiz("Q?", ["A", "B", "C", "D"], multi=True, correct_count=3)
    ps.open_quiz(lambda: None)
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ps.quiz_opened_at = base_time
    vote_time = (base_time + timedelta(seconds=1)).isoformat()
    # Alice picks A,B,D. Bob picks C,D.
    ps.votes = {
        "alice": {"option_indices": [0, 1, 3], "voted_at": vote_time},
        "bob":   {"option_indices": [2, 3], "voted_at": vote_time},
    }
    scores = MockScores()

    # First reveal correct = {A,B,C}. Alice: R=2,W=1,ratio=(2-1)/3 → ~333. Bob: R=1,W=1,ratio=0 → 0.
    ps.reveal_correct([0, 1, 2], scores)
    alice_first = scores.scores.get("alice", 0)
    assert alice_first > 0
    assert scores.scores.get("bob", 0) == 0
    assert ps.awarded_points == {"alice": alice_first}

    # Second reveal correct = {C,D}. Alice: voted A,B,D → R=1,W=2,ratio=max(0,-1/2)=0 → 0.
    # Bob: voted C,D → R=2,W=0,ratio=2/2=1 → 1000.
    ps.reveal_correct([2, 3], scores)
    assert scores.scores.get("alice", 0) == 0
    assert scores.scores.get("bob") == _MAX_POINTS
    assert ps.awarded_points == {"bob": _MAX_POINTS}


def test_reveal_correct_twice_empty_set_reverses_all():
    """If the host marks no options correct on the second reveal, all prior awards must be reversed."""
    ps = QuizState()
    ps.create_quiz("Q?", ["A", "B"])
    ps.open_quiz(lambda: None)
    base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    ps.quiz_opened_at = base_time
    vote_time = (base_time + timedelta(seconds=1)).isoformat()
    ps.votes = {"alice": {"option_indices": [0], "voted_at": vote_time}}
    scores = MockScores()

    ps.reveal_correct([0], scores)
    assert scores.scores["alice"] == _MAX_POINTS

    ps.reveal_correct([], scores)
    assert scores.scores.get("alice", 0) == 0
    assert ps.awarded_points == {}
    assert ps.quiz_correct_indices == []


def test_append_to_quiz_md(tmp_path):
    ps = QuizState()
    _make_quiz(ps)
    ps.cast_vote("pid1", option_indices=[0])

    with patch("daemon.misc.content_files.get_active_session_folder", return_value=tmp_path):
        ps.reveal_correct([0], MockScores())

    quiz_file = tmp_path / "ai-quiz.md"
    assert quiz_file.exists()
    md = quiz_file.read_text()
    assert "### Test?" in md
    assert "- [✓] A" in md
    assert "- [✗] B" in md
    assert "- [✗] C" in md
