"""
Tests for WS UUID resolution: participants can connect normally.
(Note: paused_participant_uuids concept has been removed in Phase 0 refactor)
"""
import json
import pytest
from fastapi.testclient import TestClient

from railway.app import app
from railway.shared.state import state


@pytest.fixture(autouse=True)
def clean_state():
    """Reset relevant state fields before each test."""
    state.reset()
    state.generate_session_id()
    yield
    state.reset()


def test_ws_unknown_uuid_allowed_through():
    """Unknown UUID is allowed to proceed normally — receives participant_count_updated on connect."""
    client = TestClient(app)
    with client.websocket_connect(f"/ws/{state.session_id}/brand-new-uuid") as ws:
        # On connect, server sends participant_count_updated broadcast
        msg = ws.receive_json()
        assert msg.get("type") != "session_paused"
        assert msg.get("type") == "participant_count_updated"


def test_ws_known_participant_allowed_through():
    """A known participant UUID is allowed through normally."""
    state.participant_names = {"active-uuid": "Alice"}

    client = TestClient(app)
    with client.websocket_connect(f"/ws/{state.session_id}/active-uuid") as ws:
        msg = ws.receive_json()
        assert msg.get("type") != "session_paused"
        assert msg.get("type") == "participant_count_updated"
