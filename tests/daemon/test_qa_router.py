"""Tests for daemon Q&A router."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from starlette.testclient import TestClient
from fastapi import FastAPI

from daemon.qa.router import participant_router, host_router
from daemon.qa.state import QAState
from daemon.participant.state import ParticipantState


@pytest.fixture
def fresh_qa_state():
    qas = QAState()
    with patch("daemon.qa.router.qa_state", qas):
        yield qas


@pytest.fixture
def fresh_participant_state():
    ps = ParticipantState()
    ps.participant_names = {"uuid1": "Alice", "uuid2": "Bob", "__host__": "Host"}
    ps.participant_avatars = {"uuid1": "a1.png", "uuid2": "a2.png"}
    with patch("daemon.qa.router.participant_state", ps):
        yield ps


@pytest.fixture
def mock_ws_client():
    with patch("daemon.qa.router.broadcast") as mock:
        yield mock


@pytest.fixture
def mock_host_ws():
    """Mock notify_host in qa.router."""
    with patch("daemon.qa.router.notify_host", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def participant_client(fresh_qa_state, fresh_participant_state, mock_host_ws):
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture
def host_client(fresh_qa_state, fresh_participant_state, mock_ws_client, mock_host_ws):
    app = FastAPI()
    app.include_router(host_router)
    return TestClient(app)


class TestParticipantSubmit:
    def test_submit_creates_question(self, participant_client, fresh_qa_state):
        resp = participant_client.post("/api/participant/qa/submit",
                                       json={"text": "What is Python?"},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        assert len(fresh_qa_state.questions) == 1

    def test_submit_empty_text_rejected(self, participant_client):
        resp = participant_client.post("/api/participant/qa/submit",
                                       json={"text": ""},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400

    def test_submit_long_text_rejected(self, participant_client):
        resp = participant_client.post("/api/participant/qa/submit",
                                       json={"text": "x" * 281},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400

    def test_submit_missing_pid(self, participant_client):
        resp = participant_client.post("/api/participant/qa/submit",
                                       json={"text": "Question?"})
        assert resp.status_code == 400

    def test_submit_sends_to_host(self, participant_client, mock_host_ws):
        participant_client.post("/api/participant/qa/submit",
                                json={"text": "Question?"},
                                headers={"X-Participant-ID": "uuid1"})
        assert mock_host_ws.call_count == 2
        first_msg = mock_host_ws.call_args_list[0][0][0].model_dump()
        assert first_msg["type"] == "qa_updated"
        second_msg = mock_host_ws.call_args_list[1][0][0].model_dump()
        assert second_msg["type"] == "scores_updated"


class TestParticipantUpvote:
    def test_upvote_success(self, participant_client, fresh_qa_state):
        qid = fresh_qa_state.submit("uuid1", "Question?")
        resp = participant_client.post("/api/participant/qa/upvote",
                                       json={"question_id": qid},
                                       headers={"X-Participant-ID": "uuid2"})
        assert resp.status_code == 200

    def test_upvote_self_rejected(self, participant_client, fresh_qa_state):
        qid = fresh_qa_state.submit("uuid1", "Question?")
        resp = participant_client.post("/api/participant/qa/upvote",
                                       json={"question_id": qid},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 409

    def test_upvote_duplicate_rejected(self, participant_client, fresh_qa_state):
        qid = fresh_qa_state.submit("uuid1", "Question?")
        fresh_qa_state.upvote(qid, "uuid2")
        resp = participant_client.post("/api/participant/qa/upvote",
                                       json={"question_id": qid},
                                       headers={"X-Participant-ID": "uuid2"})
        assert resp.status_code == 409

    def test_upvote_missing_question_id(self, participant_client):
        resp = participant_client.post("/api/participant/qa/upvote",
                                       json={},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 422  # Pydantic rejects missing required field


class TestHostEndpoints:
    def test_host_submit(self, host_client, fresh_qa_state, mock_ws_client):
        resp = host_client.post("/api/test-session/host/qa/submit",
                                json={"text": "Host question"})
        assert resp.status_code == 200
        assert len(fresh_qa_state.questions) == 1
        q = list(fresh_qa_state.questions.values())[0]
        assert q["author"] == "__host__"

    def test_edit_question(self, host_client, fresh_qa_state, mock_ws_client):
        qid = fresh_qa_state.submit("uuid1", "Original")
        resp = host_client.put(f"/api/test-session/host/qa/question/{qid}/text",
                               json={"text": "Edited"})
        assert resp.status_code == 200
        assert fresh_qa_state.questions[qid]["text"] == "Edited"

    def test_delete_question(self, host_client, fresh_qa_state, mock_ws_client):
        qid = fresh_qa_state.submit("uuid1", "To delete")
        resp = host_client.delete(f"/api/test-session/host/qa/question/{qid}")
        assert resp.status_code == 200
        assert qid not in fresh_qa_state.questions

    def test_toggle_answered(self, host_client, fresh_qa_state, mock_ws_client):
        qid = fresh_qa_state.submit("uuid1", "Question")
        resp = host_client.put(f"/api/test-session/host/qa/question/{qid}/answered",
                               json={"answered": True})
        assert resp.status_code == 200
        assert fresh_qa_state.questions[qid]["answered"] is True

    def test_clear(self, host_client, fresh_qa_state, mock_ws_client):
        fresh_qa_state.submit("uuid1", "Q1")
        fresh_qa_state.submit("uuid2", "Q2")
        resp = host_client.post("/api/test-session/host/qa/clear", json={})
        assert resp.status_code == 200
        assert fresh_qa_state.questions == {}

    def test_edit_nonexistent_404(self, host_client):
        resp = host_client.put("/api/test-session/host/qa/question/bad-id/text",
                               json={"text": "New"})
        assert resp.status_code == 404

    def test_host_submit_sends_broadcast(self, host_client, mock_ws_client):
        from daemon.ws_messages import QaUpdatedMsg
        host_client.post("/api/test-session/host/qa/submit",
                         json={"text": "Question"})
        assert mock_ws_client.call_count >= 1
        broadcast_msg = mock_ws_client.call_args_list[0][0][0]
        assert isinstance(broadcast_msg, QaUpdatedMsg)
