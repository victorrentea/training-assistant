"""Tests for daemon misc participant routes."""
from unittest.mock import patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.misc.router import participant_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


def test_feedback_route_sends_email_notification():
    client = _client()
    with patch("daemon.misc.router.email_notify", create=True) as notify:
        resp = client.post(
            "/api/participant/misc/feedback",
            json={"text": "Please add dark mode toggle."},
            headers={"X-Participant-ID": "p1"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    notify.assert_called_once()
    subject, body = notify.call_args.args
    assert "Participant Feedback" in subject
    assert "p1" in body
    assert "Please add dark mode toggle." in body
