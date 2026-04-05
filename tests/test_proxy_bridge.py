"""Tests for the Railway proxy bridge."""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from railway.features.ws.proxy_bridge import (
    proxy_to_daemon,
    handle_proxy_response,
    _pending_requests,
)


@pytest.fixture(autouse=True)
def clear_pending():
    """Ensure no leftover pending requests between tests."""
    _pending_requests.clear()
    yield
    _pending_requests.clear()


class TestProxyToDaemon:
    @pytest.mark.anyio
    async def test_returns_503_when_daemon_disconnected(self):
        with patch("railway.features.ws.proxy_bridge.state") as mock_state:
            mock_state.daemon_ws = None
            resp = await proxy_to_daemon("POST", "/api/participant/name", b'{"name":"Alice"}', {}, "uuid1")
            assert resp.status_code == 503

    @pytest.mark.anyio
    async def test_sends_proxy_request_and_resolves_response(self):
        mock_ws = AsyncMock()

        async def fake_send_json(msg):
            # Simulate daemon responding immediately
            req_id = msg["id"]
            await handle_proxy_response({
                "id": req_id,
                "status": 200,
                "body": '{"ok": true}',
                "content_type": "application/json",
            })

        mock_ws.send_json = fake_send_json

        with patch("railway.features.ws.proxy_bridge.state") as mock_state:
            mock_state.daemon_ws = mock_ws
            resp = await proxy_to_daemon("POST", "/api/participant/name", b'{"name":"Alice"}',
                                         {"x-participant-id": "uuid1"}, "uuid1")
            assert resp.status_code == 200
            assert b"ok" in resp.body

    @pytest.mark.anyio
    async def test_returns_503_on_timeout(self):
        mock_ws = AsyncMock()
        # send_json succeeds but no response ever comes

        with patch("railway.features.ws.proxy_bridge.state") as mock_state, \
             patch("railway.features.ws.proxy_bridge.PROXY_TIMEOUT", 0.1):
            mock_state.daemon_ws = mock_ws
            resp = await proxy_to_daemon("POST", "/api/participant/name", b'{}', {}, "uuid1")
            assert resp.status_code == 503


class TestHandleProxyResponse:
    @pytest.mark.anyio
    async def test_resolves_matching_future(self):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        _pending_requests["abc123"] = future
        await handle_proxy_response({"id": "abc123", "status": 200, "body": "ok"})
        assert future.done()
        assert future.result()["status"] == 200

    @pytest.mark.anyio
    async def test_ignores_unknown_id(self):
        # Should not raise
        await handle_proxy_response({"id": "unknown", "status": 200})

    @pytest.mark.anyio
    async def test_ignores_missing_id(self):
        # Should not raise
        await handle_proxy_response({"status": 200})
