"""Tests for POST /api/session/talk-presentation-path."""
from pathlib import Path
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
from fastapi import FastAPI

from daemon.session.router import global_router


def _client():
    app = FastAPI()
    app.include_router(global_router)
    return TestClient(app, raise_server_exceptions=False)


def _no_session_patches():
    return [
        patch("daemon.session.router.resolve_gdrive_file_url", return_value=None),
        patch("daemon.session.router.session_state.get_active_session_name", return_value=None),
        patch("daemon.session.router._get_sessions_root", return_value=None),
    ]


class TestTalkPresentationPath:
    def test_returns_204_with_no_active_session(self):
        with _no_session_patches()[0], _no_session_patches()[1], _no_session_patches()[2]:
            resp = _client().post("/api/session/talk-presentation-path",
                                  json={"path": "talk.pptx"})
        assert resp.status_code == 204

    def test_saves_slides_talk_to_session_state(self, tmp_path):
        gdrive_url = "https://drive.google.com/file/d/abc123/view"
        folder = tmp_path / "2026-04-14 My Talk"
        folder.mkdir()

        with patch("daemon.session.router.resolve_gdrive_file_url", return_value=gdrive_url), \
             patch("daemon.session.router.session_state.get_active_session_name", return_value=folder.name), \
             patch("daemon.session.router._get_sessions_root", return_value=tmp_path), \
             patch("daemon.session.router.load_session_state", return_value={}) as mock_load, \
             patch("daemon.session.router.save_session_state") as mock_save:
            resp = _client().post("/api/session/talk-presentation-path",
                                  json={"path": "/Users/victor/MyTalk.pptx"})

        assert resp.status_code == 204
        mock_save.assert_called_once()
        saved_state = mock_save.call_args[0][1]
        assert saved_state["slides_talk"]["pptx_name"] == "MyTalk.pptx"
        assert saved_state["slides_talk"]["gdrive_url"] == gdrive_url
        assert saved_state["slides_talk"]["pdf_path"].endswith("MyTalk.pdf")

    def test_saves_none_gdrive_when_not_in_drive(self, tmp_path):
        folder = tmp_path / "2026-04-14 My Talk"
        folder.mkdir()

        with patch("daemon.session.router.resolve_gdrive_file_url", return_value=None), \
             patch("daemon.session.router.session_state.get_active_session_name", return_value=folder.name), \
             patch("daemon.session.router._get_sessions_root", return_value=tmp_path), \
             patch("daemon.session.router.load_session_state", return_value={}) as mock_load, \
             patch("daemon.session.router.save_session_state") as mock_save:
            resp = _client().post("/api/session/talk-presentation-path",
                                  json={"path": "talk.pptx"})

        assert resp.status_code == 204
        saved_state = mock_save.call_args[0][1]
        assert saved_state["slides_talk"]["gdrive_url"] is None
        assert saved_state["slides_talk"]["pdf_path"].endswith("talk.pdf")
