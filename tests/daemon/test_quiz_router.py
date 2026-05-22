"""Tests for daemon quiz router — participant + host endpoints."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from daemon.participant.state import ParticipantState
from daemon.quiz.router import host_router, participant_router
from daemon.quiz.state import QuizState
from daemon.scores import Scores

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
    return TestClient(app)


def _create_quiz(client, fresh_quiz_state, fresh_scores):
    resp = client.post("/api/test-session/host/quiz/manual/submit", json={
        "question": "Which option?",
        "options": _SAMPLE_OPTIONS,
        "multi": False,
    })
    assert resp.status_code == 204


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
        resp = host_client.post("/api/test-session/host/quiz/manual/submit", json={
            "question": "Best framework?",
            "options": _SAMPLE_OPTIONS,
            "multi": False,
        })
        assert resp.status_code == 204
        notify_types = [call[0][0].type for call in mock_notify_host.call_args_list]
        assert "quiz_opened" in notify_types

    def test_create_quiz_activity_gate(self, host_client, mock_participant_state):
        mock_participant_state.current_activity = "debate"
        resp = host_client.post("/api/test-session/host/quiz/manual/submit", json={
            "question": "Q?",
            "options": _SAMPLE_OPTIONS,
            "multi": False,
        })
        assert resp.status_code == 409

    def test_create_quiz_string_options(self, host_client):
        """Options are always strings — sent and received via WS as-is."""
        resp = host_client.post("/api/test-session/host/quiz/manual/submit", json={
            "question": "Manual quiz?",
            "options": ["Alpha", "Beta", "Gamma"],
            "multi": False,
        })
        assert resp.status_code == 204


class TestHostCreateQuizOpensIt:
    def test_manual_submit_broadcasts_quiz_opened(self, host_client, fresh_quiz_state, mock_broadcast, mock_notify_host):
        resp = host_client.post("/api/test-session/host/quiz/manual/submit", json={
            "question": "Q?",
            "options": _SAMPLE_OPTIONS,
            "multi": False,
        })
        assert resp.status_code == 204

        broadcast_types = [call[0][0].type for call in mock_broadcast.call_args_list]
        assert "quiz_opened" in broadcast_types


class TestHostEndQuiz:
    def test_end_quiz(self, host_client, fresh_quiz_state, fresh_scores, mock_broadcast, mock_notify_host):
        _create_quiz(host_client, fresh_quiz_state, fresh_scores)

        resp = host_client.post("/api/test-session/host/quiz/end", json={})
        assert resp.status_code == 204

        broadcast_types = [call[0][0].type for call in mock_broadcast.call_args_list]
        assert "quiz_ended" in broadcast_types

    def test_end_quiz_no_quiz(self, host_client):
        resp = host_client.post("/api/test-session/host/quiz/end", json={})
        assert resp.status_code == 400


class TestHostRevealCorrect:
    def test_reveal_correct(self, host_client, fresh_quiz_state, fresh_scores, mock_broadcast, mock_notify_host):
        _create_quiz(host_client, fresh_quiz_state, fresh_scores)

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

        resp = host_client.post("/api/test-session/host/quiz/end/timer", json={"seconds": 45})
        assert resp.status_code == 204

        broadcast_msg = mock_broadcast.call_args_list[0][0][0]
        assert broadcast_msg.type == "quiz_end_countdown_started"
        assert broadcast_msg.seconds == 45

    def test_start_timer_no_quiz(self, host_client):
        resp = host_client.post("/api/test-session/host/quiz/end/timer", json={"seconds": 30})
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
