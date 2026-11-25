"""A participant's paste also reaches Victor Mac as a `paste_received` pill."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.misc.router import participant_router
from daemon.misc.state import misc_state
from daemon.participant.state import participant_state


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolate():
    import daemon.addon_bridge_client  # noqa: F401 — loaded before patching
    participant_state.participant_names.clear()
    misc_state.paste_texts.clear()
    with patch("daemon.misc.router.notify_host", new_callable=AsyncMock), \
         patch("daemon.addon_bridge_client.send_paste_received", return_value=True) as send:
        yield send
    participant_state.participant_names.clear()
    misc_state.paste_texts.clear()


def test_paste_is_forwarded_with_the_sender_name(client, isolate):
    participant_state.participant_names["u1"] = "Alice"
    resp = client.post("/api/participant/paste", json={"text": "hello\nworld"},
                       headers={"X-Participant-ID": "u1"})
    assert resp.status_code == 204
    isolate.assert_called_once_with("Alice", "hello\nworld")


def test_unknown_sender_is_someone_never_the_uuid(client, isolate):
    client.post("/api/participant/paste", json={"text": "x"}, headers={"X-Participant-ID": "u-123"})
    isolate.assert_called_once_with("Someone", "x")


def test_bridge_down_does_not_fail_the_paste(client, isolate):
    isolate.return_value = False
    resp = client.post("/api/participant/paste", json={"text": "x"}, headers={"X-Participant-ID": "u1"})
    assert resp.status_code == 204
