"""Tests for daemon poll router — participant + host endpoints."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from daemon.poll.state import PollState
from daemon.scores import Scores
from daemon.poll.router import participant_router, host_router, quiz_md_router
from daemon.participant.state import ParticipantState

_SAMPLE_OPTIONS = [
    {"id": "a", "text": "Option A"},
    {"id": "b", "text": "Option B"},
    {"id": "c", "text": "Option C"},
]


@pytest.fixture
def fresh_poll_state():
    """Clean PollState for each test."""
    ps = PollState()
    with patch("daemon.poll.router.poll_state", ps):
        yield ps


@pytest.fixture
def fresh_scores():
    """Clean Scores for each test."""
    s = Scores()
    with patch("daemon.poll.router.scores", s):
        yield s


@pytest.fixture
def mock_ws_client():
    """Mock ws_client for broadcast path."""
    mock = MagicMock()
    mock.send.return_value = True
    with patch("daemon.poll.router._ws_client", mock):
        yield mock


@pytest.fixture
def mock_host_ws():
    """Mock send_to_host for host WS path."""
    with patch("daemon.poll.router.send_to_host", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def mock_participant_state():
    """Clean ParticipantState patched in the router module."""
    ps = ParticipantState()
    ps.current_activity = "none"
    with patch("daemon.poll.router.participant_state", ps):
        yield ps


@pytest.fixture
def participant_client(fresh_poll_state, fresh_scores):
    """TestClient with participant poll router."""
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture
def host_client(fresh_poll_state, fresh_scores, mock_ws_client, mock_host_ws, mock_participant_state):
    """TestClient with host poll router + quiz-md router."""
    app = FastAPI()
    app.include_router(host_router)
    app.include_router(quiz_md_router)
    return TestClient(app)


# ── Helper to set up a poll in the ready state ──

def _create_and_open_poll(client, fresh_poll_state, fresh_scores):
    """Create a poll via API then open it."""
    resp = client.post("/api/test-session/poll", json={
        "question": "Which option?",
        "options": _SAMPLE_OPTIONS,
        "multi": False,
    })
    assert resp.status_code == 200
    client.post("/api/test-session/poll/open", json={})


# ──────────────────────────────────────────────
# Participant endpoint tests
# ──────────────────────────────────────────────

class TestParticipantVote:
    def test_cast_vote_single(self, participant_client, fresh_poll_state):
        """Single-select vote is accepted when poll is open."""
        fresh_poll_state.create_poll("Q?", _SAMPLE_OPTIONS)
        fresh_poll_state.open_poll(lambda: None)

        resp = participant_client.post(
            "/api/participant/poll/vote",
            json={"option_id": "a"},
            headers={"X-Participant-ID": "pid1"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_cast_vote_multi(self, participant_client, fresh_poll_state):
        """Multi-select vote is accepted when poll is open."""
        multi_opts = [
            {"id": "a", "text": "A"},
            {"id": "b", "text": "B"},
            {"id": "c", "text": "C"},
        ]
        fresh_poll_state.create_poll("Q?", multi_opts, multi=True, correct_count=2)
        fresh_poll_state.open_poll(lambda: None)

        resp = participant_client.post(
            "/api/participant/poll/vote",
            json={"option_ids": ["a", "b"]},
            headers={"X-Participant-ID": "pid1"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_cast_vote_rejected(self, participant_client, fresh_poll_state):
        """Vote on closed/no poll returns 409."""
        # Poll not created — cast_vote returns False
        resp = participant_client.post(
            "/api/participant/poll/vote",
            json={"option_id": "a"},
            headers={"X-Participant-ID": "pid1"},
        )
        assert resp.status_code == 409

    def test_cast_vote_no_pid(self, participant_client):
        """Missing X-Participant-ID returns 400."""
        resp = participant_client.post(
            "/api/participant/poll/vote",
            json={"option_id": "a"},
        )
        assert resp.status_code == 400


# ──────────────────────────────────────────────
# Host endpoint tests
# ──────────────────────────────────────────────

class TestHostCreatePoll:
    def test_create_poll(self, host_client, fresh_poll_state, mock_host_ws):
        """Create poll returns created poll and notifies host."""
        resp = host_client.post("/api/test-session/poll", json={
            "question": "Best framework?",
            "options": _SAMPLE_OPTIONS,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["poll"]["question"] == "Best framework?"
        # send_to_host called with poll_created
        mock_host_ws.assert_called_once()
        call_args = mock_host_ws.call_args[0][0]
        assert call_args["type"] == "poll_created"
        assert "poll" in call_args

    def test_create_poll_activity_gate(self, host_client, mock_participant_state):
        """Cannot create poll when another activity (debate) is active."""
        mock_participant_state.current_activity = "debate"
        resp = host_client.post("/api/test-session/poll", json={
            "question": "Q?",
            "options": _SAMPLE_OPTIONS,
        })
        assert resp.status_code == 409


class TestHostOpenPoll:
    def test_open_poll(self, host_client, fresh_poll_state, mock_ws_client, mock_host_ws):
        """Opening a poll broadcasts to participants and notifies host."""
        fresh_poll_state.create_poll("Q?", _SAMPLE_OPTIONS)

        resp = host_client.post("/api/test-session/poll/open", json={})
        assert resp.status_code == 200

        # Broadcast to participants
        assert mock_ws_client.send.call_count >= 1
        broadcast_msg = mock_ws_client.send.call_args_list[0][0][0]
        assert broadcast_msg["type"] == "broadcast"
        assert broadcast_msg["event"]["type"] == "poll_opened"

        # Notify host
        mock_host_ws.assert_called()
        host_call = mock_host_ws.call_args[0][0]
        assert host_call["type"] == "poll_opened"

    def test_open_poll_no_poll(self, host_client):
        """Open when no poll exists returns 400."""
        resp = host_client.post("/api/test-session/poll/open", json={})
        assert resp.status_code == 400


class TestHostClosePoll:
    def test_close_poll(self, host_client, fresh_poll_state, fresh_scores, mock_ws_client, mock_host_ws):
        """Closing a poll broadcasts vote_counts and notifies host."""
        _create_and_open_poll(host_client, fresh_poll_state, fresh_scores)

        resp = host_client.post("/api/test-session/poll/close", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "vote_counts" in data

        # Participants receive poll_closed broadcast
        broadcast_types = [
            call[0][0].get("event", {}).get("type")
            for call in mock_ws_client.send.call_args_list
        ]
        assert "poll_closed" in broadcast_types

    def test_close_poll_no_poll(self, host_client):
        """Close when no poll returns 400."""
        resp = host_client.post("/api/test-session/poll/close", json={})
        assert resp.status_code == 400


class TestHostRevealCorrect:
    def test_reveal_correct(self, host_client, fresh_poll_state, fresh_scores, mock_ws_client, mock_host_ws):
        """Revealing correct answers broadcasts correct_revealed + scores_updated."""
        _create_and_open_poll(host_client, fresh_poll_state, fresh_scores)

        resp = host_client.put("/api/test-session/poll/correct", json={"correct_ids": ["a"]})
        assert resp.status_code == 200

        # Two broadcasts: poll_correct_revealed + scores_updated
        broadcast_events = [
            call[0][0].get("event", {}).get("type")
            for call in mock_ws_client.send.call_args_list
            if call[0][0].get("type") == "broadcast"
        ]
        assert "poll_correct_revealed" in broadcast_events
        assert "scores_updated" in broadcast_events

        # Host also notified twice (correct_revealed + scores_updated)
        host_call_types = [call[0][0]["type"] for call in mock_host_ws.call_args_list]
        assert "poll_correct_revealed" in host_call_types
        assert "scores_updated" in host_call_types

    def test_reveal_correct_no_poll(self, host_client):
        """Reveal correct when no poll returns 400."""
        resp = host_client.put("/api/test-session/poll/correct", json={"correct_ids": ["a"]})
        assert resp.status_code == 400


class TestHostStartTimer:
    def test_start_timer(self, host_client, fresh_poll_state, mock_ws_client, mock_host_ws):
        """Starting timer broadcasts timer_started with seconds."""
        fresh_poll_state.create_poll("Q?", _SAMPLE_OPTIONS)

        resp = host_client.post("/api/test-session/poll/timer", json={"seconds": 45})
        assert resp.status_code == 200

        broadcast_msg = mock_ws_client.send.call_args_list[0][0][0]
        assert broadcast_msg["event"]["type"] == "poll_timer_started"
        assert broadcast_msg["event"]["seconds"] == 45

        host_call = mock_host_ws.call_args[0][0]
        assert host_call["type"] == "poll_timer_started"
        assert host_call["seconds"] == 45

    def test_start_timer_no_poll(self, host_client):
        """Start timer with no poll returns 400."""
        resp = host_client.post("/api/test-session/poll/timer", json={"seconds": 30})
        assert resp.status_code == 400


class TestHostDeletePoll:
    def test_delete_poll(self, host_client, fresh_poll_state, mock_participant_state, mock_ws_client, mock_host_ws):
        """Deleting a poll clears state and broadcasts poll_cleared + activity_updated."""
        fresh_poll_state.create_poll("Q?", _SAMPLE_OPTIONS)

        resp = host_client.delete("/api/test-session/poll")
        assert resp.status_code == 200
        assert fresh_poll_state.poll is None
        assert mock_participant_state.current_activity == "none"

        broadcast_types = [
            call[0][0].get("event", {}).get("type")
            for call in mock_ws_client.send.call_args_list
            if call[0][0].get("type") == "broadcast"
        ]
        assert "poll_cleared" in broadcast_types
        assert "activity_updated" in broadcast_types


class TestGetQuizMd:
    def test_get_quiz_md(self, host_client, fresh_poll_state):
        """GET /api/{session_id}/quiz-md returns quiz markdown content."""
        fresh_poll_state.quiz_md_content = "### Some quiz\n- [✓] A\n"

        resp = host_client.get("/api/test-session/quiz-md")
        assert resp.status_code == 200
        data = resp.json()
        assert "content" in data
        assert "Some quiz" in data["content"]

    def test_get_quiz_md_empty(self, host_client, fresh_poll_state):
        """GET /api/{session_id}/quiz-md returns empty string initially."""
        resp = host_client.get("/api/test-session/quiz-md")
        assert resp.status_code == 200
        assert resp.json()["content"] == ""
