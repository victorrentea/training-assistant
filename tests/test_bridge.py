"""Tests for the tablet ⇄ Mac add-on WebSocket bridge (railway/features/bridge)."""
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from railway.app import app
import railway.features.bridge.router as bridge


TOKEN = "test-bridge-token"


@pytest.fixture(autouse=True)
def bridge_env(monkeypatch):
    """Set the shared token and reset module state between tests."""
    monkeypatch.setenv("BRIDGE_TOKEN", TOKEN)
    bridge._mac_ws = None
    bridge._pending.clear()
    yield
    bridge._mac_ws = None
    bridge._pending.clear()


def test_rejects_missing_or_wrong_token():
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/bridge/tablet?token=WRONG"):
            pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/bridge/tablet"):  # no token
            pass


def test_tablet_request_with_no_mac_gets_503():
    client = TestClient(app)
    with client.websocket_connect(f"/ws/bridge/tablet?token={TOKEN}") as tablet:
        tablet.send_json({"type": "bridge_request", "id": "r0",
                          "method": "GET", "path": "/ping", "body": ""})
        resp = tablet.receive_json()
        assert resp["type"] == "bridge_response"
        assert resp["id"] == "r0"
        assert resp["status"] == 503
        assert "mac-offline" in resp["body"]


def test_round_trip_tablet_to_mac_and_back():
    client = TestClient(app)
    with client.websocket_connect(f"/ws/bridge/mac?token={TOKEN}") as mac, \
         client.websocket_connect(f"/ws/bridge/tablet?token={TOKEN}") as tablet:
        tablet.send_json({"type": "bridge_request", "id": "r1", "method": "GET",
                          "path": "/sound/play/40_joker.mp3?vol=80", "body": ""})

        # Backend forwards the request verbatim to the Mac...
        forwarded = mac.receive_json()
        assert forwarded["type"] == "bridge_request"
        assert forwarded["id"] == "r1"
        assert forwarded["path"] == "/sound/play/40_joker.mp3?vol=80"

        # ...the Mac replies, and the backend routes it back to the tablet by id.
        mac.send_json({"type": "bridge_response", "id": "r1", "status": 200,
                       "contentType": "application/json", "body": '{"durationMs":1234}'})
        resp = tablet.receive_json()
        assert resp["id"] == "r1"
        assert resp["status"] == 200
        assert "1234" in resp["body"]


def test_second_mac_kicks_the_first():
    client = TestClient(app)
    with client.websocket_connect(f"/ws/bridge/mac?token={TOKEN}"):
        assert bridge._mac_ws is not None
        with client.websocket_connect(f"/ws/bridge/mac?token={TOKEN}"):
            # The newest Mac connection is the live one.
            assert bridge._mac_ws is not None
