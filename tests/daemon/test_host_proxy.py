# tests/daemon/test_host_proxy.py
"""Tests for daemon host server and proxy module."""
from unittest.mock import patch

from starlette.testclient import TestClient

from daemon.host_server import create_app


class TestHostServerCreation:
    def test_create_app_returns_fastapi(self):
        app = create_app("http://localhost:9999")
        assert app is not None
        assert app.title == "Daemon Host Panel"

    def test_host_page_returns_html(self, tmp_path):
        """Verify /host/{session_id} returns host.html content."""
        host_html = tmp_path / "host.html"
        host_html.write_text("<html>HOST</html>")

        with patch("daemon.host_server._STATIC_DIR", tmp_path):
            app = create_app("http://localhost:9999")
            client = TestClient(app)
            resp = client.get("/host/test123")
            assert resp.status_code == 200
            assert "HOST" in resp.text

    def test_static_files_served(self, tmp_path):
        """Verify /static/ serves local files."""
        (tmp_path / "test.js").write_text("console.log('hello');")

        with patch("daemon.host_server._STATIC_DIR", tmp_path):
            app = create_app("http://localhost:9999")
            client = TestClient(app)
            resp = client.get("/static/test.js")
            assert resp.status_code == 200
            assert "hello" in resp.text

    def test_static_avatars_subdirectory(self, tmp_path):
        """Verify /static/avatars/ serves files from subdirectory."""
        avatars = tmp_path / "avatars"
        avatars.mkdir()
        (avatars / "gandalf.png").write_bytes(b"fake-png")

        with patch("daemon.host_server._STATIC_DIR", tmp_path):
            app = create_app("http://localhost:9999")
            client = TestClient(app)
            resp = client.get("/static/avatars/gandalf.png")
            assert resp.status_code == 200
            assert resp.content == b"fake-png"
