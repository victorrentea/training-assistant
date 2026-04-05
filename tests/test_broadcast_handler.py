"""Tests for the Railway broadcast fan-out handler."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from railway.features.ws.router import _handle_broadcast


class TestHandleBroadcast:
    @pytest.mark.anyio
    async def test_fans_out_event_to_participants(self):
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        mock_state = MagicMock()
        mock_state.participants = {"uuid1": ws1, "uuid2": ws2}

        with patch("railway.features.ws.router.state", mock_state):
            await _handle_broadcast({"event": {"type": "wordcloud_updated", "words": {"hello": 1}}})

        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()
        sent = json.loads(ws1.send_text.call_args[0][0])
        assert sent["type"] == "wordcloud_updated"
        assert sent["words"] == {"hello": 1}

    @pytest.mark.anyio
    async def test_includes_host(self):
        participant_ws = AsyncMock()
        host_ws = AsyncMock()
        mock_state = MagicMock()
        mock_state.participants = {
            "uuid1": participant_ws,
            "__host__": host_ws,
        }

        with patch("railway.features.ws.router.state", mock_state):
            await _handle_broadcast({"event": {"type": "test"}})

        participant_ws.send_text.assert_called_once()
        host_ws.send_text.assert_called_once()

    @pytest.mark.anyio
    async def test_skips_other_special_connections(self):
        participant_ws = AsyncMock()
        host_ws = AsyncMock()
        daemon_ws = AsyncMock()
        mock_state = MagicMock()
        mock_state.participants = {
            "uuid1": participant_ws,
            "__host__": host_ws,
            "__daemon_mirror__": daemon_ws,
        }

        with patch("railway.features.ws.router.state", mock_state):
            await _handle_broadcast({"event": {"type": "test"}})

        participant_ws.send_text.assert_called_once()
        host_ws.send_text.assert_called_once()
        daemon_ws.send_text.assert_not_called()

    @pytest.mark.anyio
    async def test_handles_dead_connections(self):
        good_ws = AsyncMock()
        bad_ws = AsyncMock()
        bad_ws.send_text.side_effect = Exception("connection closed")
        mock_state = MagicMock()
        mock_state.participants = {"uuid1": good_ws, "uuid2": bad_ws}

        with patch("railway.features.ws.router.state", mock_state):
            await _handle_broadcast({"event": {"type": "test"}})

        good_ws.send_text.assert_called_once()

    @pytest.mark.anyio
    async def test_ignores_missing_event(self):
        mock_state = MagicMock()
        mock_state.participants = {"uuid1": AsyncMock()}

        with patch("railway.features.ws.router.state", mock_state):
            await _handle_broadcast({})  # no event key

        mock_state.participants["uuid1"].send_text.assert_not_called()
