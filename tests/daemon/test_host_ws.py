"""Tests for daemon host WS push module."""
import pytest
from unittest.mock import AsyncMock, patch

import daemon.host_ws as host_ws_mod
from daemon.host_ws import set_host_ws, clear_host_ws, send_to_host


class TestHostWs:
    def setup_method(self):
        host_ws_mod._host_ws = None

    def test_set_and_clear(self):
        mock_ws = AsyncMock()
        set_host_ws(mock_ws)
        assert host_ws_mod._host_ws is mock_ws
        clear_host_ws()
        assert host_ws_mod._host_ws is None

    @pytest.mark.anyio
    async def test_send_to_host_delivers_message(self):
        mock_ws = AsyncMock()
        set_host_ws(mock_ws)
        await send_to_host({"type": "test", "data": 123})
        mock_ws.send_text.assert_called_once()
        import json
        sent = json.loads(mock_ws.send_text.call_args[0][0])
        assert sent["type"] == "test"
        assert sent["data"] == 123

    @pytest.mark.anyio
    async def test_send_to_host_noop_when_disconnected(self):
        # Should not raise
        await send_to_host({"type": "test"})

    @pytest.mark.anyio
    async def test_send_to_host_handles_exception(self):
        mock_ws = AsyncMock()
        mock_ws.send_text.side_effect = Exception("connection closed")
        set_host_ws(mock_ws)
        # Should not raise
        await send_to_host({"type": "test"})
