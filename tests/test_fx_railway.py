"""Tests for the public /fx/* relay.

Two things are load-bearing here and both have bitten this repo before: the
route must be registered before the /{session_id}/{tab} catch-all, and the path
must be constrained before it reaches a proxy that resolves `../` at the far
end.
"""
import pytest
from unittest.mock import AsyncMock, patch
from starlette.testclient import TestClient
from urllib.parse import unquote

from railway.app import app

client = TestClient(app)


@pytest.fixture
def proxy():
    with patch("railway.features.fx.router.proxy_to_daemon", new_callable=AsyncMock) as p:
        p.return_value = "relayed"
        yield p


async def _send_raw_path(path: str) -> int:
    """Drive the ASGI app directly with a literal, unnormalised request path,
    bypassing httpx's client-side URL normalisation entirely.

    Only used for the traversal-shaped cases below. ``TestClient`` is
    httpx-backed, and httpx collapses `..` dot-segments out of a URL string
    client-side (RFC 3986 5.3) before the request ever leaves the process —
    so ``client.get("/fx/../../etc/passwd")`` is actually sent to the server
    as ``GET /etc/passwd`` and never touches ``/fx/*`` at all. A test built on
    ``TestClient`` would prove nothing about the traversal case; worse, it
    would look like it did. The router's regex is the real boundary, since
    `proxy_to_daemon` hands this string to an httpx call at the daemon end,
    where `../` gets resolved against the daemon's own base URL — so this
    helper reconstructs the ASGI scope a raw (non-normalising) client would
    actually produce, and calls the app directly.
    """
    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": unquote(path),
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 123),
        "http_version": "1.1",
    }
    await app(scope, receive, send)
    return next(m["status"] for m in messages if m["type"] == "http.response.start")


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
        "/fx/ABC123",
        "/fx/abc-123",
        "/fx/abc.123",
        "/fx/" + "a" * 41,
    ])
    def test_a_path_outside_the_alphabet_never_reaches_the_daemon(self, proxy, bad):
        r = client.get(bad)
        assert r.status_code == 404
        proxy.assert_not_awaited()

    @pytest.mark.anyio
    @pytest.mark.parametrize("bad", [
        "/fx/../../etc/passwd",
        "/fx/%2e%2e/secret",
    ])
    async def test_a_traversal_path_is_rejected_even_when_it_reaches_the_router(self, proxy, bad):
        """Traversal-shaped inputs, driven straight at the ASGI app (see
        `_send_raw_path`) instead of through `TestClient` — httpx would
        normalise the `..` out of the URL before the request even reaches the
        router, which would hide the very thing this test exists to prove. Do
        not "simplify" this back into a `client.get(bad)` call; that silently
        stops testing the traversal case."""
        status = await _send_raw_path(bad)
        assert status == 404
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

    def test_the_session_catch_all_still_works(self, proxy):
        """Registering the fx router earlier must not shadow ordinary
        participant pages: /notasession/quiz must still be handled by the
        session catch-all (a 307 to the neutral landing, pinned explicitly via
        follow_redirects=False rather than guessed at), not relayed to the
        daemon as if "notasession" were an FX token."""
        r = client.get("/notasession/quiz", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == "/?error=invalid"
        proxy.assert_not_awaited()
