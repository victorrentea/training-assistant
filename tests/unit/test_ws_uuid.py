"""
Tests for WS UUID resolution: participants can connect normally.
(Note: paused_participant_uuids concept has been removed in Phase 0 refactor)
"""
import json
import pytest
from fastapi.testclient import TestClient

from main import app
from core.state import state


@pytest.fixture(autouse=True)
def clean_state():
    """Reset relevant state fields before each test."""
    state.participant_names = {}
    state.participants = {}
    yield
    state.participant_names = {}


def test_ws_unknown_uuid_allowed_through():
    """Unknown UUID is allowed to proceed normally."""
    client = TestClient(app)
    with client.websocket_connect("/ws/brand-new-uuid") as ws:
        # Send set_name to trigger normal flow
        ws.send_json({"type": "set_name", "name": "Dave"})
        # Receive a message — it should be state (not an error/paused message)
        msg = ws.receive_json()
        assert msg.get("type") != "session_paused"


def test_ws_known_participant_allowed_through():
    """A known participant UUID is allowed through normally."""
    state.participant_names = {"active-uuid": "Alice"}

    client = TestClient(app)
    with client.websocket_connect("/ws/active-uuid") as ws:
        ws.send_json({"type": "set_name", "name": "Alice"})
        msg = ws.receive_json()
        assert msg.get("type") != "session_paused"
