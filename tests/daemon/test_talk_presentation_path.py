"""Tests for POST /api/session/talk-presentation-path."""
from unittest.mock import patch, AsyncMock
from starlette.testclient import TestClient
from fastapi import FastAPI

from daemon.session.router import global_router


def _client():
    app = FastAPI()
    app.include_router(global_router)
    return TestClient(app, raise_server_exceptions=False)


class TestTalkPresentationPath:
    def test_returns_204_with_no_active_session(self):
        with patch("daemon.session.router.resolve_gdrive_file_url", return_value=None), \
             patch("daemon.session.router.session_state.get_active_session_name", return_value=None), \
             patch("daemon.session.router._get_sessions_root", return_value=None), \
             patch("daemon.session.router.asyncio.create_task", side_effect=lambda c: c.close()):
            resp = _client().post("/api/session/talk-presentation-path",
                                  json={"path": "talk.pptx"})
        assert resp.status_code == 204

    def test_saves_talk_presentation_fields_to_session_state(self, tmp_path):
        gdrive_url = "https://drive.google.com/file/d/abc123/view"
        expected_export_url = "https://docs.google.com/presentation/d/abc123/export/pdf"
        folder = tmp_path / "2026-04-14 My Talk"
        folder.mkdir()

        with patch("daemon.session.router.resolve_gdrive_file_url", return_value=gdrive_url), \
             patch("daemon.session.router.session_state.get_active_session_name", return_value=folder.name), \
             patch("daemon.session.router._get_sessions_root", return_value=tmp_path), \
             patch("daemon.session.router.load_session_state", return_value={}) as mock_load, \
             patch("daemon.session.router.save_session_state") as mock_save, \
             patch("daemon.session.router.asyncio.create_task", side_effect=lambda c: c.close()):
            resp = _client().post("/api/session/talk-presentation-path",
                                  json={"path": "/Users/victor/MyTalk.pptx"})

        assert resp.status_code == 204
        mock_save.assert_called_once()
        saved_state = mock_save.call_args[0][1]
        assert saved_state["talk_presentation_url"] == expected_export_url
        assert saved_state["talk_presentation_slug"] == "mytalk"

    def test_no_download_when_not_in_google_drive(self, tmp_path):
        folder = tmp_path / "2026-04-14 My Talk"
        folder.mkdir()

        with patch("daemon.session.router.resolve_gdrive_file_url", return_value=None), \
             patch("daemon.session.router.session_state.get_active_session_name", return_value=folder.name), \
             patch("daemon.session.router._get_sessions_root", return_value=tmp_path), \
             patch("daemon.session.router.load_session_state", return_value={}), \
             patch("daemon.session.router.save_session_state") as mock_save, \
             patch("daemon.session.router.asyncio.create_task") as mock_task:
            resp = _client().post("/api/session/talk-presentation-path",
                                  json={"path": "talk.pptx"})

        assert resp.status_code == 204
        saved_state = mock_save.call_args[0][1]
        assert saved_state["talk_presentation_url"] is None
        assert saved_state["talk_presentation_slug"] == "talk"
        mock_task.assert_not_called()
