"""
Tests for WS UUID resolution: participants can connect normally.
(Note: paused_participant_uuids concept has been removed in Phase 0 refactor)
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from railway.app import app
from railway.shared.state import state


@pytest.fixture(autouse=True)
def clean_state():
    """Reset relevant state fields before each test."""
    import railway.shared.messaging as _msg
    _msg._participant_update_throttle._last_run = 0.0
    _msg._participant_update_throttle._pending_handle = None
    state.reset()
    state.session_id = "e2etst"
    yield
    state.reset()


def test_ws_unknown_uuid_allowed_through():
    """Unknown UUID is allowed to proceed normally — receives active_participants_count_updated on connect."""
    client = TestClient(app)
    with client.websocket_connect(f"/ws/{state.session_id}/brand-new-uuid") as ws:
        # On connect, server sends active_participants_count_updated broadcast
        msg = ws.receive_json()
        assert msg.get("type") != "session_paused"
        assert msg.get("type") == "active_participants_count_updated"


def test_ws_known_participant_allowed_through():
    """A known participant UUID is allowed through normally."""
    state.participant_names = {"active-uuid": "Alice"}

    client = TestClient(app)
    with client.websocket_connect(f"/ws/{state.session_id}/active-uuid") as ws:
        msg = ws.receive_json()
        assert msg.get("type") != "session_paused"
        assert msg.get("type") == "active_participants_count_updated"


def test_ws_notifies_daemon_about_presence_changes():
    client = TestClient(app)
    with patch("railway.features.ws.router.push_to_daemon", new=AsyncMock(return_value=True)) as push_mock:
        with client.websocket_connect(f"/ws/{state.session_id}/presence-uuid") as ws:
            assert ws.receive_json().get("type") == "active_participants_count_updated"

        sent_messages = [call.args[0] for call in push_mock.await_args_list]
        assert {"type": "participant_presence", "uuid": "presence-uuid", "online": True} in sent_messages
        assert {"type": "participant_presence", "uuid": "presence-uuid", "online": False} in sent_messages


def test_ws_forwards_browser_tz_query_param_to_daemon():
    """Browser timezone passed via WS query string is included in the daemon presence push."""
    client = TestClient(app)
    with patch("railway.features.ws.router.push_to_daemon", new=AsyncMock(return_value=True)) as push_mock:
        with client.websocket_connect(f"/ws/{state.session_id}/tz-uuid?tz=Asia/Kolkata") as ws:
            assert ws.receive_json().get("type") == "active_participants_count_updated"

        online_msgs = [
            call.args[0] for call in push_mock.await_args_list
            if call.args[0].get("type") == "participant_presence" and call.args[0].get("online") is True
        ]
        assert online_msgs, "expected an online presence push"
        assert online_msgs[0].get("tz") == "Asia/Kolkata"


def test_ws_participant_count_uses_connected_participants():
    """Count reflects currently connected (live WS) non-host participants, not offline known names.

    Commit 1abe5ca0: switched from participant_names to participants so count stays accurate
    even when Railway restarts and participant_names haven't been re-synced from daemon yet.
    """
    # These are known but offline — should NOT be counted
    state.participant_names = {
        "offline-1": "Alice",
        "offline-2": "Bob",
        "offline-3": "Charlie",
    }

    client = TestClient(app)
    with client.websocket_connect(f"/ws/{state.session_id}/only-live-client") as ws:
        msg = ws.receive_json()
        assert msg.get("type") == "active_participants_count_updated"
        assert msg.get("count") == 1  # only the one live WS connection
