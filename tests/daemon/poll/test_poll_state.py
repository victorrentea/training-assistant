"""Tests for poll state extension — votes, helpers, reset."""
import pytest

from daemon.poll.state import PollData, PollState


@pytest.fixture
def started_state():
    s = PollState()
    s.data = PollData(question="Q?", options=["A", "B", "C"], multi=False, public=False)
    s.started = True
    return s


class TestCastVote:
    def test_rejects_when_not_started(self):
        s = PollState()
        s.data = PollData(question="Q?", options=["A", "B"], multi=False, public=False)
        s.started = False
        assert s.cast_vote("p1", [0]) is False
        assert s.votes == {}

    def test_rejects_when_no_data(self):
        s = PollState()
        s.started = True
        assert s.cast_vote("p1", [0]) is False

    def test_rejects_out_of_range_index(self, started_state):
        assert started_state.cast_vote("p1", [5]) is False
        assert started_state.votes == {}

    def test_rejects_negative_index(self, started_state):
        assert started_state.cast_vote("p1", [-1]) is False

    def test_rejects_multi_select_when_not_multi(self, started_state):
        assert started_state.cast_vote("p1", [0, 1]) is False

    def test_accepts_single_vote(self, started_state):
        assert started_state.cast_vote("p1", [1]) is True
        assert started_state.votes["p1"]["option_indices"] == [1]
        assert "voted_at" in started_state.votes["p1"]

    def test_accepts_multi_vote_when_multi(self, started_state):
        started_state.data = PollData(question="Q?", options=["A", "B", "C"], multi=True, public=False)
        assert started_state.cast_vote("p1", [0, 2]) is True
        assert started_state.votes["p1"]["option_indices"] == [0, 2]

    def test_overwrites_previous_vote(self, started_state):
        started_state.cast_vote("p1", [0])
        started_state.cast_vote("p1", [2])
        assert started_state.votes["p1"]["option_indices"] == [2]
        assert len(started_state.votes) == 1

    def test_empty_options_removes_entry(self, started_state):
        started_state.data = PollData(question="Q?", options=["A", "B"], multi=True, public=False)
        started_state.cast_vote("p1", [0, 1])
        started_state.cast_vote("p1", [])
        assert "p1" not in started_state.votes


class TestVoteCounts:
    def test_empty_votes(self, started_state):
        assert started_state.vote_counts() == [0, 0, 0]

    def test_single_votes(self, started_state):
        started_state.cast_vote("p1", [0])
        started_state.cast_vote("p2", [1])
        started_state.cast_vote("p3", [1])
        assert started_state.vote_counts() == [1, 2, 0]

    def test_multi_votes(self, started_state):
        started_state.data = PollData(question="Q?", options=["A", "B", "C"], multi=True, public=False)
        started_state.cast_vote("p1", [0, 1])
        started_state.cast_vote("p2", [1, 2])
        assert started_state.vote_counts() == [1, 2, 1]

    def test_cache_invalidated_on_vote(self, started_state):
        started_state.cast_vote("p1", [0])
        assert started_state.vote_counts() == [1, 0, 0]
        started_state.cast_vote("p2", [2])
        assert started_state.vote_counts() == [1, 0, 1]

    def test_no_options_returns_empty(self):
        s = PollState()
        assert s.vote_counts() == []


class TestDistinctVoterCount:
    def test_zero_voters(self, started_state):
        assert started_state.distinct_voter_count() == 0

    def test_counts_distinct_uuids(self, started_state):
        started_state.cast_vote("p1", [0])
        started_state.cast_vote("p2", [1])
        started_state.cast_vote("p1", [2])  # same voter, new vote
        assert started_state.distinct_voter_count() == 2


class TestReset:
    def test_reset_wipes_everything(self, started_state):
        started_state.opened_at = "2026-05-23T10:00:00Z"
        started_state.cast_vote("p1", [0])
        started_state.cast_vote("p2", [1])

        started_state.reset()

        assert started_state.data is None
        assert started_state.started is False
        assert started_state.opened_at is None
        assert started_state.votes == {}
        assert started_state.vote_counts() == []
