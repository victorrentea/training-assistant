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
def mock_ws_client():
    mock = MagicMock()
    mock.send.return_value = True
    with patch("daemon.leaderboard.router._ws_client", mock):
        yield mock


@pytest.fixture
def mock_host_ws():
    with patch("daemon.leaderboard.router.send_to_host", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def client(fresh_scores, fresh_participant_state, mock_ws_client, mock_host_ws):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestShowLeaderboard:
    def test_show_leaderboard(self, client, fresh_scores, mock_ws_client, mock_host_ws):
        fresh_scores.add_score("p1", 300)
        fresh_scores.add_score("p2", 100)
        fresh_scores.add_score("p3", 200)

        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        # ws_client.send called with broadcast containing leaderboard_revealed
        mock_ws_client.send.assert_called_once()
        call_arg = mock_ws_client.send.call_args[0][0]
        assert call_arg["type"] == "broadcast"
        assert call_arg["event"]["type"] == "leaderboard_revealed"
        # Entries sorted by score desc
        entries = call_arg["event"]["entries"]
        assert entries[0]["score"] == 300
        assert entries[1]["score"] == 200
        assert entries[2]["score"] == 100
        # send_to_host called
        mock_host_ws.assert_called_once()
        # total_participants is correct
        assert call_arg["event"]["total_participants"] == 3

    def test_show_leaderboard_with_names(self, client, fresh_scores, fresh_participant_state, mock_ws_client, mock_host_ws):
        fresh_scores.add_score("p1", 500)
        fresh_scores.add_score("p2", 300)
        fresh_participant_state.participant_names["p1"] = "Alice"
        fresh_participant_state.participant_names["p2"] = "Bob"

        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        call_arg = mock_ws_client.send.call_args[0][0]
        entries = call_arg["event"]["entries"]
        assert entries[0]["name"] == "Alice"
        assert entries[1]["name"] == "Bob"

    def test_show_leaderboard_empty(self, client, fresh_scores, mock_ws_client, mock_host_ws):
        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        call_arg = mock_ws_client.send.call_args[0][0]
        assert call_arg["event"]["entries"] == []
        assert call_arg["event"]["total_participants"] == 0

    def test_show_leaderboard_top5_only(self, client, fresh_scores, mock_ws_client, mock_host_ws):
        for i in range(7):
            fresh_scores.add_score(f"p{i}", (i + 1) * 100)

        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        call_arg = mock_ws_client.send.call_args[0][0]
        entries = call_arg["event"]["entries"]
        assert len(entries) == 5
        # Top score is 700 (p6)
        assert entries[0]["score"] == 700

    def test_show_leaderboard_unknown_name_fallback(self, client, fresh_scores, mock_ws_client, mock_host_ws):
        fresh_scores.add_score("unknown-uuid", 100)

        resp = client.post("/api/test-session/host/leaderboard/show")

        assert resp.status_code == 200
        call_arg = mock_ws_client.send.call_args[0][0]
        entries = call_arg["event"]["entries"]
        assert entries[0]["name"] == "???"


class TestHideLeaderboard:
    def test_hide_leaderboard(self, client, mock_ws_client, mock_host_ws):
        resp = client.post("/api/test-session/host/leaderboard/hide")

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        mock_ws_client.send.assert_called_once()
        call_arg = mock_ws_client.send.call_args[0][0]
        assert call_arg["type"] == "broadcast"
        assert call_arg["event"]["type"] == "leaderboard_hide"
        mock_host_ws.assert_called_once()


class TestResetScores:
    def test_reset_scores(self, client, fresh_scores, mock_ws_client, mock_host_ws):
        fresh_scores.add_score("p1", 500)
        fresh_scores.add_score("p2", 300)

        resp = client.delete("/api/test-session/host/scores")

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        # Scores cleared
        assert fresh_scores.snapshot() == {}
        # Broadcast scores_updated with empty scores
        mock_ws_client.send.assert_called_once()
        call_arg = mock_ws_client.send.call_args[0][0]
        assert call_arg["type"] == "broadcast"
        assert call_arg["event"]["type"] == "scores_updated"
        assert call_arg["event"]["scores"] == {}
        # send_to_host called
        mock_host_ws.assert_called_once()
