"""Tests for POST /api/session/talk-presentation-path."""
import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
from fastapi import FastAPI

from daemon.session.router import global_router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(global_router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def mock_session_state():
    """Mock session state and meta for all tests."""
    with patch("daemon.session.router.session_state") as mock_state, \
         patch("daemon.session.router.load_session_meta") as mock_meta, \
         patch("daemon.session.router._get_sessions_root") as mock_root:
        mock_root.return_value = MagicMock()
        mock_state.get_active_session_name.return_value = "2026-04-13 My Talk"
        mock_meta.return_value = {"session_type": "talk"}
        yield {"state": mock_state, "meta": mock_meta, "root": mock_root}


class TestTalkPresentationPath:
    def test_returns_204_in_talk_mode(self, client):
        with patch("daemon.session.router.resolve_gdrive_file_url", return_value=None):
            resp = client.post("/api/session/talk-presentation-path",
                               json={"path": "/Users/victor/GDrive/talk.pptx"})
        assert resp.status_code == 204

    def test_returns_400_when_not_talk(self, client, mock_session_state):
        mock_session_state["meta"].return_value = {"session_type": "workshop"}
        resp = client.post("/api/session/talk-presentation-path",
                           json={"path": "/Users/victor/GDrive/talk.pptx"})
        assert resp.status_code == 400

    def test_returns_400_when_no_active_session(self, client, mock_session_state):
        mock_session_state["state"].get_active_session_name.return_value = None
        resp = client.post("/api/session/talk-presentation-path",
                           json={"path": "/Users/victor/GDrive/talk.pptx"})
        assert resp.status_code == 400

    def test_logs_gdrive_url_when_resolved(self, client):
        with patch("daemon.session.router.resolve_gdrive_file_url",
                   return_value="https://drive.google.com/file/d/abc123/view") as mock_resolve:
            resp = client.post("/api/session/talk-presentation-path",
                               json={"path": "/Users/victor/GDrive/talk.pptx"})
        assert resp.status_code == 204
        mock_resolve.assert_called_once_with("/Users/victor/GDrive/talk.pptx")
