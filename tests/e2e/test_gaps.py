"""E2E tests covering remaining gaps in routers/codereview.py and routers/ws.py."""
import pytest
from conftest import api


@pytest.fixture(autouse=False)
def clean_codereview(server_url):
    api(server_url, "delete", "/api/codereview")
    yield
    api(server_url, "delete", "/api/codereview")


@pytest.fixture(autouse=False)
def clean_poll(server_url):
    api(server_url, "delete", "/api/poll")
    yield
    api(server_url, "delete", "/api/poll")


# ═══════════════════════════════════════════════════════════════════════
# routers/codereview.py gaps
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.usefixtures("clean_codereview")
class TestCodeReviewGaps:
    def test_create_empty_snippet(self, server_url):
        resp = api(server_url, "post", "/api/codereview",
                   json={"snippet": "", "language": "java"})
        assert resp.status_code in (400, 422)

    def test_create_with_language(self, server_url):
        resp = api(server_url, "post", "/api/codereview",
                   json={"snippet": "int x = 1;", "language": "java"})
        assert resp.status_code == 200

    def test_create_without_language(self, server_url):
        resp = api(server_url, "post", "/api/codereview",
                   json={"snippet": "def foo(): pass"})
        assert resp.status_code == 200

    def test_status_to_reviewing(self, server_url):
        api(server_url, "post", "/api/codereview",
            json={"snippet": "int x = 1;", "language": "java"})
        resp = api(server_url, "put", "/api/codereview/status",
                   json={"open": False})
        assert resp.status_code == 200

    def test_confirm_line_no_session(self, server_url):
        resp = api(server_url, "put", "/api/codereview/confirm-line",
                   json={"line": 1})
        assert resp.status_code in (400, 404)

    def test_confirm_line_in_reviewing(self, server_url):
        api(server_url, "post", "/api/codereview",
            json={"snippet": "line1\nline2\nline3", "language": "text"})
        api(server_url, "put", "/api/codereview/status",
            json={"open": False})
        resp = api(server_url, "put", "/api/codereview/confirm-line",
                   json={"line": 1})
        assert resp.status_code == 200

    def test_delete_codereview(self, server_url):
        api(server_url, "post", "/api/codereview",
            json={"snippet": "code", "language": "java"})
        resp = api(server_url, "delete", "/api/codereview")
        assert resp.status_code == 200

    def test_create_then_delete_then_confirm_fails(self, server_url):
        api(server_url, "post", "/api/codereview",
            json={"snippet": "code", "language": "java"})
        api(server_url, "delete", "/api/codereview")
        resp = api(server_url, "put", "/api/codereview/confirm-line", json={"line": 1})
        assert resp.status_code == 400
