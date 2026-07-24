"""Tests for the host→participant notification endpoint (Direction A).

Covers: broadcast REFUSED while the capability is off, delivered (with text +
timestamp) while on, empty/whitespace text rejected, and the no-UUID guarantee
on the emitted `host_notification` frame.
"""
import pytest
from unittest.mock import patch
from starlette.testclient import TestClient
from fastapi import FastAPI

from daemon.attention.router import host_router
from daemon.participant.state import participant_state
from daemon.ws_messages import HostNotificationMsg


@pytest.fixture
def notify_client():
    app = FastAPI()
    app.include_router(host_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    participant_state.attention_enabled = True
    yield
    participant_state.attention_enabled = False


class TestHostNotification:
    def test_broadcasts_text_and_timestamp_when_enabled(self, notify_client):
        with patch("daemon.attention.router.broadcast") as mock_bcast:
            r = notify_client.post("/api/sid1/host/attention/notify", json={"text": "Resuming now 🙌"})
            assert r.status_code == 204
            mock_bcast.assert_called_once()
            sent = mock_bcast.call_args[0][0]
            assert isinstance(sent, HostNotificationMsg)
            dump = sent.model_dump()
            assert dump["type"] == "host_notification"
            assert dump["text"] == "Resuming now 🙌"
            assert isinstance(dump["at"], str) and dump["at"]  # ISO timestamp present

    def test_refused_when_disabled(self, notify_client):
        participant_state.attention_enabled = False
        with patch("daemon.attention.router.broadcast") as mock_bcast:
            r = notify_client.post("/api/sid1/host/attention/notify", json={"text": "hi"})
            assert r.status_code == 409
            mock_bcast.assert_not_called()

    def test_empty_text_rejected(self, notify_client):
        with patch("daemon.attention.router.broadcast") as mock_bcast:
            r = notify_client.post("/api/sid1/host/attention/notify", json={"text": "   "})
            assert r.status_code == 400
            mock_bcast.assert_not_called()

    def test_broadcast_payload_has_no_uuid(self, notify_client):
        """SECURITY: host_notification is text + timestamp only — no per-user id."""
        with patch("daemon.attention.router.broadcast") as mock_bcast:
            notify_client.post("/api/sid1/host/attention/notify", json={"text": "hello"})
            dump = mock_bcast.call_args[0][0].model_dump()
            assert set(dump.keys()) == {"type", "text", "at"}
