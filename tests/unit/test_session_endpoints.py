# tests/unit/test_session_endpoints.py
import base64
import os
import pytest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from main import app
from core.state import state

client = TestClient(app)

_host_user = os.environ.get("HOST_USERNAME", "host")
_host_pass = os.environ.get("HOST_PASSWORD", "host")
HOST_AUTH = {"Authorization": "Basic " + base64.b64encode(f"{_host_user}:{_host_pass}".encode()).decode()}

@pytest.fixture(autouse=True)
def reset_session_id():
    old = state.session_id
    state.session_id = None
    yield
    state.session_id = old


def test_session_active_returns_false_and_null_when_no_session():
    response = client.get("/api/session/active")
    assert response.status_code == 200
    body = response.json()
    assert body == {"active": False, "session_id": None}


def test_session_active_returns_true_and_id_when_active():
    state.session_id = "abc123"
    response = client.get("/api/session/active")
    body = response.json()
    assert body == {"active": True, "session_id": "abc123"}


def test_session_create_returns_session_id_and_updates_state(monkeypatch):
    import features.session.router as sr
    monkeypatch.setattr(sr, "push_to_daemon", AsyncMock())
    monkeypatch.setattr(sr, "broadcast_state", AsyncMock())
    response = client.post("/api/session/create", json={"name": "2026-03-29 WS"},
                           headers=HOST_AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "session_id" in body
    assert len(body["session_id"]) == 6
    assert state.session_id == body["session_id"]


def test_session_end_clears_session_id(monkeypatch):
    import features.session.router as sr
    monkeypatch.setattr(sr, "push_to_daemon", AsyncMock())
    monkeypatch.setattr(sr, "broadcast_state", AsyncMock())
    state.session_id = "alive123"
    response = client.post("/api/session/end", headers=HOST_AUTH)
    assert response.status_code == 200
    assert state.session_id is None


def test_host_session_page_requires_auth():
    response = client.get("/host/abc123")
    assert response.status_code == 401


def test_host_session_page_serves_html_when_authed():
    response = client.get("/host/abc123", headers=HOST_AUTH)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_session_folders_is_public():
    """Folders endpoint must be public so the browser-side blocker JS can call it."""
    response = client.get("/api/session/folders")
    assert response.status_code == 200
    assert "folders" in response.json()
