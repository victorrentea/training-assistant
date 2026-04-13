"""Tests for POST /api/session/talk-presentation-path."""
from unittest.mock import patch
from starlette.testclient import TestClient
from fastapi import FastAPI

from daemon.session.router import global_router


def _client():
    app = FastAPI()
    app.include_router(global_router)
    return TestClient(app, raise_server_exceptions=False)


class TestTalkPresentationPath:
    def test_returns_204_with_no_gdrive_match(self):
        with patch("daemon.session.router.resolve_gdrive_file_url", return_value=None):
            resp = _client().post("/api/session/talk-presentation-path",
                                  json={"path": "talk.pptx"})
        assert resp.status_code == 204

    def test_returns_204_with_gdrive_url(self):
        with patch("daemon.session.router.resolve_gdrive_file_url",
                   return_value="https://drive.google.com/file/d/abc123/view") as mock_resolve:
            resp = _client().post("/api/session/talk-presentation-path",
                                  json={"path": "talk.pptx"})
        assert resp.status_code == 204
        mock_resolve.assert_called_once_with("talk.pptx")
