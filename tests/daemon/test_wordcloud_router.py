"""Tests for daemon word cloud router."""
import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
from fastapi import FastAPI

from daemon.wordcloud.router import participant_router, host_router
from daemon.wordcloud.state import WordCloudState
from daemon.participant.state import ParticipantState


@pytest.fixture
def fresh_wc_state():
    """Clean WordCloudState for each test."""
    wcs = WordCloudState()
    with patch("daemon.wordcloud.router.wordcloud_state", wcs):
        yield wcs


@pytest.fixture
def fresh_participant_state():
    """Clean ParticipantState with wordcloud activity."""
    ps = ParticipantState()
    ps.current_activity = "wordcloud"
    with patch("daemon.wordcloud.router.participant_state", ps):
        yield ps


@pytest.fixture
def mock_ws_client():
    """Mock broadcast for host-direct path."""
    with patch("daemon.wordcloud.router.broadcast") as mock:
        yield mock


@pytest.fixture
def participant_client(fresh_wc_state, fresh_participant_state):
    """TestClient with participant wordcloud router."""
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture
def host_client(fresh_wc_state, mock_ws_client):
    """TestClient with host wordcloud router."""
    app = FastAPI()
    app.include_router(host_router)
    return TestClient(app)


class TestParticipantSubmitWord:
    def test_word_added_and_counted(self, participant_client, fresh_wc_state):
        resp = participant_client.post("/api/participant/wordcloud/word",
                                       json={"word": "Hello"},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200
        assert fresh_wc_state.words.get("hello") == 1  # lowercased

    def test_duplicate_word_increments(self, participant_client, fresh_wc_state):
        participant_client.post("/api/participant/wordcloud/word",
                                json={"word": "test"},
                                headers={"X-Participant-ID": "uuid1"})
        participant_client.post("/api/participant/wordcloud/word",
                                json={"word": "test"},
                                headers={"X-Participant-ID": "uuid2"})
        assert fresh_wc_state.words.get("test") == 2

    def test_empty_word_rejected(self, participant_client):
        resp = participant_client.post("/api/participant/wordcloud/word",
                                       json={"word": ""},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400

    def test_long_word_rejected(self, participant_client):
        resp = participant_client.post("/api/participant/wordcloud/word",
                                       json={"word": "a" * 41},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400

    def test_missing_participant_id_rejected(self, participant_client):
        resp = participant_client.post("/api/participant/wordcloud/word",
                                       json={"word": "test"})
        assert resp.status_code == 400

    def test_activity_gate_rejects_when_not_wordcloud(self, participant_client, fresh_participant_state):
        fresh_participant_state.current_activity = "poll"
        resp = participant_client.post("/api/participant/wordcloud/word",
                                       json={"word": "test"},
                                       headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 409

    def test_word_order_newest_first(self, participant_client, fresh_wc_state):
        participant_client.post("/api/participant/wordcloud/word",
                                json={"word": "first"},
                                headers={"X-Participant-ID": "uuid1"})
        participant_client.post("/api/participant/wordcloud/word",
                                json={"word": "second"},
                                headers={"X-Participant-ID": "uuid1"})
        assert fresh_wc_state.word_order[0] == "second"
        assert fresh_wc_state.word_order[1] == "first"


class TestHostEndpoints:
    # Host router prefix is /api/{session_id}/wordcloud — use "test-session" as session_id
    def test_host_word_submission(self, host_client, fresh_wc_state, mock_ws_client):
        resp = host_client.post("/api/test-session/host/wordcloud/word", json={"word": "Hello"})
        assert resp.status_code == 200
        assert fresh_wc_state.words.get("hello") == 1
        # Verify WS broadcast event was sent
        assert mock_ws_client.call_count == 1  # broadcast only

    def test_set_topic(self, host_client, fresh_wc_state, mock_ws_client):
        resp = host_client.post("/api/test-session/host/wordcloud/topic", json={"topic": "AI trends"})
        assert resp.status_code == 200
        assert fresh_wc_state.topic == "AI trends"
        assert mock_ws_client.call_count == 1

    def test_clear(self, host_client, fresh_wc_state, mock_ws_client):
        fresh_wc_state.words = {"hello": 1}
        fresh_wc_state.word_order = ["hello"]
        fresh_wc_state.topic = "test"
        resp = host_client.post("/api/test-session/host/wordcloud/clear", json={})
        assert resp.status_code == 200
        assert fresh_wc_state.words == {}
        assert fresh_wc_state.word_order == []
        assert fresh_wc_state.topic == ""

    def test_host_word_sends_broadcast_event(self, host_client, mock_ws_client):
        from daemon.ws_messages import WordcloudUpdatedMsg
        host_client.post("/api/test-session/host/wordcloud/word", json={"word": "test"})
        assert mock_ws_client.call_count >= 1
        broadcast_msg = mock_ws_client.call_args_list[0][0][0]
        assert isinstance(broadcast_msg, WordcloudUpdatedMsg)
        assert broadcast_msg.model_dump()["type"] == "wordcloud_updated"
        assert broadcast_msg.model_dump()["words"] == {"test": 1}
