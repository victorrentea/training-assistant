"""Tests for daemon leaderboard router."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from daemon.leaderboard.router import router
from daemon.participant.state import ParticipantState
from daemon.scores import Scores


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
    def test_show_leaderboard(self, client, fresh_scores, mock_broadcast):
        fresh_scores.add_score("p1", 300)
        fresh_scores.add_score("p2", 100)
        fresh_scores.add_score("p3", 200)

        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert entries[0]["score"] == 300
        assert entries[1]["score"] == 200
        assert entries[2]["score"] == 100
        # broadcast called with LeaderboardRevealedMsg
        mock_broadcast.assert_called_once()
        assert mock_broadcast.call_args[0][0].type == "leaderboard_revealed"

    def test_show_leaderboard_with_names(self, client, fresh_scores, fresh_participant_state, mock_broadcast):
        fresh_scores.add_score("p1", 500)
        fresh_scores.add_score("p2", 300)
        fresh_participant_state.participant_names["p1"] = "Alice"
        fresh_participant_state.participant_names["p2"] = "Bob"

        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert entries[0]["name"] == "Alice"
        assert entries[1]["name"] == "Bob"

    def test_show_leaderboard_empty(self, client, fresh_scores, mock_broadcast):
        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        assert resp.json()["entries"] == []

    def test_show_leaderboard_top5_only(self, client, fresh_scores, mock_broadcast):
        for i in range(7):
            fresh_scores.add_score(f"p{i}", (i + 1) * 100)

        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) == 5
        assert entries[0]["score"] == 700

    def test_show_leaderboard_unknown_name_fallback(self, client, fresh_scores, mock_broadcast):
        fresh_scores.add_score("unknown-uuid", 100)

        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        assert resp.json()["entries"][0]["name"] == "???"

    def test_show_leaderboard_rank_assigned(self, client, fresh_scores, mock_broadcast):
        fresh_scores.add_score("p1", 500)
        fresh_scores.add_score("p2", 300)

        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert entries[0]["rank"] == 1
        assert entries[1]["rank"] == 2


class TestResetScores:
    def test_reset_scores(self, client, fresh_scores, mock_broadcast, mock_notify_host):
        fresh_scores.add_score("p1", 500)
        fresh_scores.add_score("p2", 300)

        resp = client.delete("/api/test-session/host/scores")

        assert resp.status_code == 204
        assert resp.content == b""
        # Scores cleared
        assert fresh_scores.snapshot() == {}
        # broadcast called with ScoresUpdatedMsg with empty scores
        mock_broadcast.assert_called_once()
        msg = mock_broadcast.call_args[0][0]
        assert msg.type == "scores_updated"
        assert msg.scores == {}
        # notify_host called
        mock_notify_host.assert_called_once()
