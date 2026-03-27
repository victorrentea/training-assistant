"""
Tests for WS UUID resolution: paused session participants receive session_paused message.
"""
import json
import pytest
from fastapi.testclient import TestClient

from main import app
from core.state import state


@pytest.fixture(autouse=True)
def clean_state():
    """Reset relevant state fields before each test."""
    state.paused_participant_uuids = set()
    state.participant_names = {}
    state.participants = {}
    yield
    state.paused_participant_uuids = set()
    state.participant_names = {}


def test_ws_session_paused_for_paused_uuid():
    """UUID in paused_participant_uuids receives session_paused message."""
    state.paused_participant_uuids = {"paused-uuid-1"}

    client = TestClient(app)
    with client.websocket_connect("/ws/paused-uuid-1") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "session_paused"
        assert "reconnect" in msg["message"].lower() or "paused" in msg["message"].lower()


def test_ws_unknown_uuid_allowed_through():
    """Unknown UUID (not in paused set) is allowed to proceed normally."""
    state.paused_participant_uuids = set()

    client = TestClient(app)
    with client.websocket_connect("/ws/brand-new-uuid") as ws:
        # Send set_name to trigger normal flow
        ws.send_json({"type": "set_name", "name": "Dave"})
        # Receive a message — it should NOT be session_paused
        msg = ws.receive_json()
        assert msg.get("type") != "session_paused"


def test_ws_known_participant_not_in_paused_allowed_through():
    """A known participant UUID not in paused set is allowed through normally."""
    state.paused_participant_uuids = {"other-paused-uuid"}
    state.participant_names = {"active-uuid": "Alice"}

    client = TestClient(app)
    with client.websocket_connect("/ws/active-uuid") as ws:
        ws.send_json({"type": "set_name", "name": "Alice"})
        msg = ws.receive_json()
        assert msg.get("type") != "session_paused"
