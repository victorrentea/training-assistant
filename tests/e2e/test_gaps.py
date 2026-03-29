"""E2E tests covering remaining gaps in routers/codereview.py and routers/ws.py."""
import pytest
from conftest import api, sapi


@pytest.fixture(autouse=False)
def clean_codereview(server_url):
    sapi(server_url, "delete", "/codereview")
    yield
    sapi(server_url, "delete", "/codereview")


@pytest.fixture(autouse=False)
def clean_poll(server_url):
    sapi(server_url, "delete", "/poll")
    yield
    sapi(server_url, "delete", "/poll")


# ═══════════════════════════════════════════════════════════════════════
# routers/codereview.py gaps
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("clean_codereview")
class TestCodeReviewGaps:
    def test_create_empty_snippet(self, server_url):
        resp = sapi(server_url, "post", "/codereview",
                   json={"snippet": "", "language": "java"})
        assert resp.status_code in (400, 422)

    def test_create_with_language(self, server_url):
        resp = sapi(server_url, "post", "/codereview",
                   json={"snippet": "int x = 1;", "language": "java"})
        assert resp.status_code == 200

    def test_create_without_language(self, server_url):
        resp = sapi(server_url, "post", "/codereview",
                   json={"snippet": "def foo(): pass"})
        assert resp.status_code == 200

    def test_status_to_reviewing(self, server_url):
        sapi(server_url, "post", "/codereview",
            json={"snippet": "int x = 1;", "language": "java"})
        resp = sapi(server_url, "put", "/codereview/status",
                   json={"open": False})
        assert resp.status_code == 200

    def test_confirm_line_no_session(self, server_url):
        resp = sapi(server_url, "put", "/codereview/confirm-line",
                   json={"line": 1})
        assert resp.status_code in (400, 404)

    def test_confirm_line_in_reviewing(self, server_url):
        sapi(server_url, "post", "/codereview",
            json={"snippet": "line1\nline2\nline3", "language": "text"})
        sapi(server_url, "put", "/codereview/status",
            json={"open": False})
        resp = sapi(server_url, "put", "/codereview/confirm-line",
                   json={"line": 1})
        assert resp.status_code == 200

    def test_delete_codereview(self, server_url):
        sapi(server_url, "post", "/codereview",
            json={"snippet": "code", "language": "java"})
        resp = sapi(server_url, "delete", "/codereview")
        assert resp.status_code == 200

    def test_create_then_delete_then_confirm_fails(self, server_url):
        sapi(server_url, "post", "/codereview",
            json={"snippet": "code", "language": "java"})
        sapi(server_url, "delete", "/codereview")
        resp = sapi(server_url, "put", "/codereview/confirm-line", json={"line": 1})
        assert resp.status_code == 400
