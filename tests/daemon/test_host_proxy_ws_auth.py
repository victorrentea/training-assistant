"""The local host panel's socket reaches the relay with the daemon's credentials.

The relay admits a __host__ socket only from a proven trainer (an anonymous one
would kick the real panel off). The panel served by the daemon on loopback has no
credentials of its own, so the daemon's proxy vouches for it.
"""
import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock

import websockets

from daemon import host_proxy


class _Stop(Exception):
    pass


def _proxy(monkeypatch, path, client_headers):
    monkeypatch.setenv("HOST_USERNAME", "trainer")
    monkeypatch.setenv("HOST_PASSWORD", "s3cret")
    seen = {}

    def fake_connect(url, additional_headers=None, ssl=None):
        seen["url"] = url
        seen["headers"] = dict(additional_headers or {})
        raise _Stop()  # the proxy logs it and closes the client socket

    monkeypatch.setattr(websockets, "connect", fake_connect)
    client = MagicMock()
    client.headers = client_headers
    client.accept = AsyncMock()
    client.close = AsyncMock()
    asyncio.run(host_proxy.proxy_websocket(client, path, "ws://relay"))
    client.close.assert_awaited()
    return seen


def _basic(user, password):
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def test_host_socket_carries_the_daemon_credentials(monkeypatch):
    seen = _proxy(monkeypatch, "sess01/__host__", {})
    assert seen["url"] == "ws://relay/ws/sess01/__host__"
    assert seen["headers"]["Authorization"] == _basic("trainer", "s3cret")


def test_host_socket_uses_the_daemon_credentials_over_the_browser_ones(monkeypatch):
    seen = _proxy(monkeypatch, "sess01/__host__", {"authorization": _basic("someone", "else")})
    assert seen["headers"]["Authorization"] == _basic("trainer", "s3cret")


def test_other_sockets_only_forward_what_the_browser_sent(monkeypatch):
    assert "Authorization" not in _proxy(monkeypatch, "sess01/pax-1", {})["headers"]
    sent = _basic("someone", "else")
    assert _proxy(monkeypatch, "sess01/pax-1", {"authorization": sent})["headers"]["Authorization"] == sent
