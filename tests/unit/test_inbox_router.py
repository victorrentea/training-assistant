import base64
import hmac
import json
import time
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from railway.features.inbox.router import router
from railway.shared import state as state_module

app = FastAPI()
app.include_router(router)
client = TestClient(app)

# base64-encoded secret (as AgentMail/Svix provides it)
GOOD_SECRET = "dGVzdC1zZWNyZXQta2V5LTE2Yg=="


def _signed_request(body: dict, secret: str = GOOD_SECRET) -> tuple[bytes, dict]:
    """Return (body_bytes, svix_headers) for a properly signed webhook request."""
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    msg_id = "msg_test123"
    timestamp = str(int(time.time()))
    key = base64.b64decode(secret)
    signed = f"{msg_id}.{timestamp}.".encode() + body_bytes
    sig = base64.b64encode(hmac.new(key, signed, "sha256").digest()).decode()
    headers = {
        "svix-id": msg_id,
        "svix-timestamp": timestamp,
        "svix-signature": f"v1,{sig}",
        "content-type": "application/json",
    }
    return body_bytes, headers


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("AGENTMAIL_WEBHOOK_SECRET", GOOD_SECRET)
    monkeypatch.setenv("CLAUDE_INBOX_WS_TOKEN", "ws-token-xyz")
    state_module.state.claude_inbox_ws = None


class TestWebhookAuth:
    def test_missing_secret_returns_403(self):
        resp = client.post("/webhook/agentmail", json={"event_type": "message.received"})
        assert resp.status_code == 403

    def test_wrong_signature_returns_403(self):
        body = {"event_type": "message.received"}
        body_bytes, headers = _signed_request(body, secret=base64.b64encode(b"wrong-key-padding-x").decode())
        resp = client.post("/webhook/agentmail", content=body_bytes, headers=headers)
        assert resp.status_code == 403

    def test_correct_secret_returns_200(self):
        body = {"event_type": "message.received", "thread": {"senders": ["victorrentea@gmail.com"]}}
        body_bytes, headers = _signed_request(body)
        resp = client.post("/webhook/agentmail", content=body_bytes, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestWebhookForwarding:
    def test_non_message_event_is_ignored(self):
        body = {"event_type": "message.sent"}
        body_bytes, headers = _signed_request(body)
        resp = client.post("/webhook/agentmail", content=body_bytes, headers=headers)
        assert resp.status_code == 200
        assert resp.json().get("ignored") is True

    def test_forwards_to_listener_when_connected(self):
        mock_ws = AsyncMock()
        state_module.state.claude_inbox_ws = mock_ws

        body = {"event_type": "message.received", "thread": {"senders": ["victorrentea@gmail.com"]}}
        body_bytes, headers = _signed_request(body)
        resp = client.post("/webhook/agentmail", content=body_bytes, headers=headers)
        assert resp.status_code == 200
        mock_ws.send_text.assert_called_once_with(json.dumps({"type": "email_received"}))

    def test_no_listener_connected_still_returns_200(self):
        state_module.state.claude_inbox_ws = None
        body = {"event_type": "message.received", "thread": {"senders": ["victorrentea@gmail.com"]}}
        body_bytes, headers = _signed_request(body)
        resp = client.post("/webhook/agentmail", content=body_bytes, headers=headers)
        assert resp.status_code == 200

    def test_clears_state_when_listener_send_fails(self):
        mock_ws = AsyncMock()
        mock_ws.send_text.side_effect = Exception("boom")
        state_module.state.claude_inbox_ws = mock_ws

        body = {"event_type": "message.received", "thread": {"senders": ["victorrentea@gmail.com"]}}
        body_bytes, headers = _signed_request(body)
        resp = client.post("/webhook/agentmail", content=body_bytes, headers=headers)
        assert resp.status_code == 200
        assert state_module.state.claude_inbox_ws is None
