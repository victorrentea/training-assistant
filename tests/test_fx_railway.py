"""Tests for the public /fx/* relay.

Two things are load-bearing here and both have bitten this repo before: the
route must be registered before the /{session_id}/{tab} catch-all, and the path
must be constrained before it reaches a proxy that resolves `../` at the far
end.
"""
import pytest
from unittest.mock import AsyncMock, patch
from starlette.testclient import TestClient

from railway.app import app

client = TestClient(app)


@pytest.fixture
def proxy():
    with patch("railway.features.fx.router.proxy_to_daemon", new_callable=AsyncMock) as p:
        p.return_value = "relayed"
        yield p


class TestRelay:
    def test_a_get_reaches_the_daemon_under_the_participant_prefix(self, proxy):
        client.get("/fx/abc123def456")
        assert proxy.await_args.kwargs["path"] == "/api/participant/fx/abc123def456"
        assert proxy.await_args.kwargs["method"] == "GET"

    def test_a_post_to_fire_is_relayed(self, proxy):
        client.post("/fx/abc123def456/fire")
        assert proxy.await_args.kwargs["path"] == "/api/participant/fx/abc123def456/fire"
        assert proxy.await_args.kwargs["method"] == "POST"

    def test_the_image_subpath_is_relayed(self, proxy):
        client.get("/fx/abc123def456/image")
        assert proxy.await_args.kwargs["path"] == "/api/participant/fx/abc123def456/image"


class TestPathConstraint:
    @pytest.mark.parametrize("bad", [
        "/fx/../../etc/passwd",
        "/fx/%2e%2e/secret",
        "/fx/ABC123",
        "/fx/abc-123",
        "/fx/abc.123",
        "/fx/" + "a" * 41,
    ])
    def test_a_path_outside_the_alphabet_never_reaches_the_daemon(self, proxy, bad):
        r = client.get(bad)
        assert r.status_code == 404
        proxy.assert_not_awaited()

    def test_an_empty_token_is_refused(self, proxy):
        assert client.get("/fx/").status_code == 404
        proxy.assert_not_awaited()


class TestRouteOrdering:
    def test_fx_is_not_swallowed_by_the_session_catch_all(self, proxy):
        """/{session_id}/{tab} matches any two-segment path. If the fx router is
        registered after it, /fx/<token> becomes session "fx", tab "<token>"."""
        client.get("/fx/abc123def456")
        proxy.assert_awaited_once()

    def test_the_session_catch_all_still_works(self):
        """Registering earlier must not shadow ordinary participant pages."""
        r = client.get("/notasession/quiz")
        assert r.status_code in (302, 404)
