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
        with patch.dict(
            "daemon.misc.router.participant_state.participant_names",
            {"p1": "Alice"},
            clear=True,
        ):
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
    assert "Alice" in body
    assert "Please add dark mode toggle." in body


def test_feedback_route_uses_session_stack_name_fallback():
    client = _client()
    with patch("daemon.misc.router.email_notify", create=True) as notify:
        with patch("daemon.misc.router.misc_state.session_name", None):
            with patch(
                "daemon.misc.router.session_shared_state.get_session_stack",
                return_value=[{"name": "2026-04-06 Architecture Masterclass"}],
            ):
                resp = client.post(
                    "/api/participant/misc/feedback",
                    json={"text": "Need bigger poll buttons."},
                    headers={"X-Participant-ID": "p2"},
                )
    assert resp.status_code == 200
    subject, body = notify.call_args.args
    assert "2026-04-06 Architecture Masterclass" in subject
    assert "Session: 2026-04-06 Architecture Masterclass" in body
