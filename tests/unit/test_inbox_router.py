import json
import os
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from railway.features.inbox.router import router
from railway.shared import state as state_module

app = FastAPI()
app.include_router(router)
client = TestClient(app)

GOOD_SECRET = "test-secret-abc"


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("AGENTMAIL_WEBHOOK_SECRET", GOOD_SECRET)
    monkeypatch.setenv("CLAUDE_INBOX_WS_TOKEN", "ws-token-xyz")
    state_module.state.claude_inbox_ws = None


class TestWebhookAuth:
    def test_missing_secret_returns_403(self):
        resp = client.post("/webhook/agentmail", json={"event_type": "message.received"})
        assert resp.status_code == 403

    def test_wrong_secret_returns_403(self):
        resp = client.post(
            "/webhook/agentmail",
            json={"event_type": "message.received"},
            headers={"x-webhook-secret": "wrong"},
        )
        assert resp.status_code == 403

    def test_correct_secret_returns_200(self):
        resp = client.post(
            "/webhook/agentmail",
            json={"event_type": "message.received"},
            headers={"x-webhook-secret": GOOD_SECRET},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestWebhookForwarding:
    def test_non_message_event_is_ignored(self):
        resp = client.post(
            "/webhook/agentmail",
            json={"event_type": "message.sent"},
            headers={"x-webhook-secret": GOOD_SECRET},
        )
        assert resp.status_code == 200
        assert resp.json().get("ignored") is True

    def test_forwards_to_listener_when_connected(self):
        mock_ws = AsyncMock()
        state_module.state.claude_inbox_ws = mock_ws

        resp = client.post(
            "/webhook/agentmail",
            json={"event_type": "message.received"},
            headers={"x-webhook-secret": GOOD_SECRET},
        )
        assert resp.status_code == 200
        mock_ws.send_text.assert_called_once_with(json.dumps({"type": "email_received"}))

    def test_no_listener_connected_still_returns_200(self):
        state_module.state.claude_inbox_ws = None
        resp = client.post(
            "/webhook/agentmail",
            json={"event_type": "message.received"},
            headers={"x-webhook-secret": GOOD_SECRET},
        )
        assert resp.status_code == 200

    def test_clears_state_when_listener_send_fails(self):
        mock_ws = AsyncMock()
        mock_ws.send_text.side_effect = Exception("boom")
        state_module.state.claude_inbox_ws = mock_ws

        resp = client.post(
            "/webhook/agentmail",
            json={"event_type": "message.received"},
            headers={"x-webhook-secret": GOOD_SECRET},
        )
        assert resp.status_code == 200
        assert state_module.state.claude_inbox_ws is None
