"""Tests for daemon leaderboard router."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from daemon.scores import Scores
from daemon.participant.state import ParticipantState
from daemon.leaderboard.router import router


@pytest.fixture
def fresh_scores():
    s = Scores()
    with patch("daemon.leaderboard.router.scores", s):
        yield s


@pytest.fixture
def fresh_participant_state():
    ps = ParticipantState()
    with patch("daemon.leaderboard.router.participant_state", ps):
        yield ps


@pytest.fixture
def mock_broadcast():
    with patch("daemon.leaderboard.router.broadcast") as mock:
        yield mock


@pytest.fixture
def mock_notify_host():
    with patch("daemon.leaderboard.router.notify_host", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def client(fresh_scores, fresh_participant_state, mock_broadcast, mock_notify_host):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestShowLeaderboard:
    def test_show_leaderboard(self, client, fresh_scores, mock_broadcast, mock_notify_host):
        fresh_scores.add_score("p1", 300)
        fresh_scores.add_score("p2", 100)
        fresh_scores.add_score("p3", 200)

        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        # broadcast called with LeaderboardRevealedMsg
        mock_broadcast.assert_called_once()
        msg = mock_broadcast.call_args[0][0]
        assert msg.type == "leaderboard_revealed"
        # Positions sorted by score desc
        positions = msg.positions
        assert positions[0]["score"] == 300
        assert positions[1]["score"] == 200
        assert positions[2]["score"] == 100
        # notify_host called
        mock_notify_host.assert_called_once()

    def test_show_leaderboard_with_names(self, client, fresh_scores, fresh_participant_state, mock_broadcast, mock_notify_host):
        fresh_scores.add_score("p1", 500)
        fresh_scores.add_score("p2", 300)
        fresh_participant_state.participant_names["p1"] = "Alice"
        fresh_participant_state.participant_names["p2"] = "Bob"

        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        msg = mock_broadcast.call_args[0][0]
        positions = msg.positions
        assert positions[0]["name"] == "Alice"
        assert positions[1]["name"] == "Bob"

    def test_show_leaderboard_empty(self, client, fresh_scores, mock_broadcast, mock_notify_host):
        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        msg = mock_broadcast.call_args[0][0]
        assert msg.positions == []

    def test_show_leaderboard_top5_only(self, client, fresh_scores, mock_broadcast, mock_notify_host):
        for i in range(7):
            fresh_scores.add_score(f"p{i}", (i + 1) * 100)

        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        msg = mock_broadcast.call_args[0][0]
        positions = msg.positions
        assert len(positions) == 5
        # Top score is 700 (p6)
        assert positions[0]["score"] == 700

    def test_show_leaderboard_unknown_name_fallback(self, client, fresh_scores, mock_broadcast, mock_notify_host):
        fresh_scores.add_score("unknown-uuid", 100)

        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        msg = mock_broadcast.call_args[0][0]
        positions = msg.positions
        assert positions[0]["name"] == "???"

    def test_show_leaderboard_rank_assigned(self, client, fresh_scores, mock_broadcast, mock_notify_host):
        fresh_scores.add_score("p1", 500)
        fresh_scores.add_score("p2", 300)

        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        msg = mock_broadcast.call_args[0][0]
        positions = msg.positions
        assert positions[0]["rank"] == 1
        assert positions[1]["rank"] == 2


class TestResetScores:
    def test_reset_scores(self, client, fresh_scores, mock_broadcast, mock_notify_host):
        fresh_scores.add_score("p1", 500)
        fresh_scores.add_score("p2", 300)

        resp = client.delete("/api/test-session/host/scores")

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        # Scores cleared
        assert fresh_scores.snapshot() == {}
        # broadcast called with ScoresUpdatedMsg with empty scores
        mock_broadcast.assert_called_once()
        msg = mock_broadcast.call_args[0][0]
        assert msg.type == "scores_updated"
        assert msg.scores == {}
        # notify_host called
        mock_notify_host.assert_called_once()
