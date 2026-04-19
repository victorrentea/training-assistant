"""Tests for daemon poll router — participant + host endpoints."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from daemon.poll.state import PollState
from daemon.scores import Scores
from daemon.poll.router import participant_router, host_router
from daemon.participant.state import ParticipantState

_SAMPLE_OPTIONS = ["Option A", "Option B", "Option C"]


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
def mock_broadcast():
    with patch("daemon.poll.router.broadcast") as mock:
        yield mock


@pytest.fixture
def mock_notify_host():
    with patch("daemon.poll.router.notify_host", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def mock_participant_state():
    ps = ParticipantState()
    ps.current_activity = "none"
    with patch("daemon.poll.router.participant_state", ps):
        yield ps


@pytest.fixture
def participant_client(fresh_poll_state, fresh_scores):
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture
def host_client(fresh_poll_state, fresh_scores, mock_broadcast, mock_notify_host, mock_participant_state):
    app = FastAPI()
    app.include_router(host_router)
    return TestClient(app)


def _create_poll(client, fresh_poll_state, fresh_scores):
    resp = client.post("/api/test-session/host/poll/manual/submit", json={
        "question": "Which option?",
        "options": _SAMPLE_OPTIONS,
        "multi": False,
    })
    assert resp.status_code == 204


# ──────────────────────────────────────────────
# Participant endpoint tests
# ──────────────────────────────────────────────

class TestParticipantVote:
    def test_cast_vote_single(self, participant_client, fresh_poll_state):
        fresh_poll_state.create_poll("Q?", _SAMPLE_OPTIONS)
        fresh_poll_state.open_poll(lambda: None)

        resp = participant_client.post(
            "/api/participant/poll/vote",
            json={"options": [0]},
            headers={"X-Participant-ID": "pid1"},
        )
        assert resp.status_code == 204

    def test_cast_vote_multi(self, participant_client, fresh_poll_state):
        fresh_poll_state.create_poll("Q?", _SAMPLE_OPTIONS, multi=True, correct_count=2)
        fresh_poll_state.open_poll(lambda: None)

        resp = participant_client.post(
            "/api/participant/poll/vote",
            json={"options": [0, 1]},
            headers={"X-Participant-ID": "pid1"},
        )
        assert resp.status_code == 204

    def test_cast_vote_rejected(self, participant_client, fresh_poll_state):
        resp = participant_client.post(
            "/api/participant/poll/vote",
            json={"options": [0]},
            headers={"X-Participant-ID": "pid1"},
        )
        assert resp.status_code == 409

    def test_cast_vote_no_pid(self, participant_client):
        resp = participant_client.post(
            "/api/participant/poll/vote",
            json={"options": [0]},
        )
        assert resp.status_code == 400


# ──────────────────────────────────────────────
# Host endpoint tests
# ──────────────────────────────────────────────

class TestHostCreatePoll:
    def test_create_poll(self, host_client, fresh_poll_state, mock_notify_host):
        resp = host_client.post("/api/test-session/host/poll/manual/submit", json={
            "question": "Best framework?",
            "options": _SAMPLE_OPTIONS,
            "multi": False,
        })
        assert resp.status_code == 204
        notify_types = [call[0][0].type for call in mock_notify_host.call_args_list]
        assert "poll_opened" in notify_types

    def test_create_poll_activity_gate(self, host_client, mock_participant_state):
        mock_participant_state.current_activity = "debate"
        resp = host_client.post("/api/test-session/host/poll/manual/submit", json={
            "question": "Q?",
            "options": _SAMPLE_OPTIONS,
            "multi": False,
        })
        assert resp.status_code == 409

    def test_create_poll_string_options(self, host_client):
        """Options are always strings — sent and received via WS as-is."""
        resp = host_client.post("/api/test-session/host/poll/manual/submit", json={
            "question": "Manual poll?",
            "options": ["Alpha", "Beta", "Gamma"],
            "multi": False,
        })
        assert resp.status_code == 204


class TestHostCreatePollOpensIt:
    def test_manual_submit_broadcasts_poll_opened(self, host_client, fresh_poll_state, mock_broadcast, mock_notify_host):
        resp = host_client.post("/api/test-session/host/poll/manual/submit", json={
            "question": "Q?",
            "options": _SAMPLE_OPTIONS,
            "multi": False,
        })
        assert resp.status_code == 204

        broadcast_types = [call[0][0].type for call in mock_broadcast.call_args_list]
        assert "poll_opened" in broadcast_types


class TestHostEndPoll:
    def test_end_poll(self, host_client, fresh_poll_state, fresh_scores, mock_broadcast, mock_notify_host):
        _create_poll(host_client, fresh_poll_state, fresh_scores)

        resp = host_client.post("/api/test-session/host/poll/end", json={})
        assert resp.status_code == 204

        broadcast_types = [call[0][0].type for call in mock_broadcast.call_args_list]
        assert "poll_ended" in broadcast_types

    def test_end_poll_no_poll(self, host_client):
        resp = host_client.post("/api/test-session/host/poll/end", json={})
        assert resp.status_code == 400


class TestHostRevealCorrect:
    def test_reveal_correct(self, host_client, fresh_poll_state, fresh_scores, mock_broadcast, mock_notify_host):
        _create_poll(host_client, fresh_poll_state, fresh_scores)

        resp = host_client.put("/api/test-session/host/poll/correct", json={"correct_indices": [0]})
        assert resp.status_code == 204

        broadcast_types = [call[0][0].type for call in mock_broadcast.call_args_list]
        assert "poll_correct_revealed" in broadcast_types
        assert "scores_updated" in broadcast_types

        host_msg_types = [call[0][0].type for call in mock_notify_host.call_args_list]
        assert "poll_correct_revealed" in host_msg_types

    def test_reveal_correct_no_poll(self, host_client):
        resp = host_client.put("/api/test-session/host/poll/correct", json={"correct_indices": [0]})
        assert resp.status_code == 400


class TestHostStartTimer:
    def test_start_timer(self, host_client, fresh_poll_state, mock_broadcast, mock_notify_host):
        fresh_poll_state.create_poll("Q?", _SAMPLE_OPTIONS)

        resp = host_client.post("/api/test-session/host/poll/end/timer", json={"seconds": 45})
        assert resp.status_code == 204

        broadcast_msg = mock_broadcast.call_args_list[0][0][0]
        assert broadcast_msg.type == "poll_end_countdown_started"
        assert broadcast_msg.seconds == 45

    def test_start_timer_no_poll(self, host_client):
        resp = host_client.post("/api/test-session/host/poll/end/timer", json={"seconds": 30})
        assert resp.status_code == 400


class TestHostDeletePoll:
    def test_delete_poll(self, host_client, fresh_poll_state, mock_participant_state, mock_broadcast, mock_notify_host):
        fresh_poll_state.create_poll("Q?", _SAMPLE_OPTIONS)

        resp = host_client.delete("/api/test-session/host/poll")
        assert resp.status_code == 204
        assert fresh_poll_state.poll is None
        assert mock_participant_state.current_activity == "none"

        broadcast_types = [call[0][0].type for call in mock_broadcast.call_args_list]
        assert "poll_cleared" in broadcast_types
        assert "activity_updated" in broadcast_types


