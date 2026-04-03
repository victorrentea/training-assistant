"""Tests for the Railway broadcast fan-out handler."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from features.ws.router import _handle_broadcast, _handle_wordcloud_state_sync, _handle_score_award


class TestHandleBroadcast:
    @pytest.mark.anyio
    async def test_fans_out_event_to_participants(self):
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        mock_state = MagicMock()
        mock_state.participants = {"uuid1": ws1, "uuid2": ws2}

        with patch("features.ws.router.state", mock_state):
            await _handle_broadcast({"event": {"type": "wordcloud_updated", "words": {"hello": 1}}})

        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()
        sent = json.loads(ws1.send_text.call_args[0][0])
        assert sent["type"] == "wordcloud_updated"
        assert sent["words"] == {"hello": 1}

    @pytest.mark.anyio
    async def test_skips_host_and_overlay(self):
        participant_ws = AsyncMock()
        host_ws = AsyncMock()
        overlay_ws = AsyncMock()
        mock_state = MagicMock()
        mock_state.participants = {
            "uuid1": participant_ws,
            "__host__": host_ws,
            "__overlay__": overlay_ws,
        }

        with patch("features.ws.router.state", mock_state):
            await _handle_broadcast({"event": {"type": "test"}})

        participant_ws.send_text.assert_called_once()
        host_ws.send_text.assert_not_called()
        overlay_ws.send_text.assert_not_called()

    @pytest.mark.anyio
    async def test_handles_dead_connections(self):
        good_ws = AsyncMock()
        bad_ws = AsyncMock()
        bad_ws.send_text.side_effect = Exception("connection closed")
        mock_state = MagicMock()
        mock_state.participants = {"uuid1": good_ws, "uuid2": bad_ws}

        with patch("features.ws.router.state", mock_state):
            await _handle_broadcast({"event": {"type": "test"}})

        good_ws.send_text.assert_called_once()

    @pytest.mark.anyio
    async def test_ignores_missing_event(self):
        mock_state = MagicMock()
        mock_state.participants = {"uuid1": AsyncMock()}

        with patch("features.ws.router.state", mock_state):
            await _handle_broadcast({})  # no event key

        mock_state.participants["uuid1"].send_text.assert_not_called()


class TestHandleWordcloudStateSync:
    @pytest.mark.anyio
    async def test_updates_appstate(self):
        mock_state = MagicMock()
        with patch("features.ws.router.state", mock_state):
            await _handle_wordcloud_state_sync({
                "words": {"hello": 2},
                "word_order": ["hello"],
                "topic": "greetings",
            })
        assert mock_state.wordcloud_words == {"hello": 2}
        assert mock_state.wordcloud_word_order == ["hello"]
        assert mock_state.wordcloud_topic == "greetings"


class TestHandleScoreAward:
    @pytest.mark.anyio
    async def test_awards_score_and_broadcasts(self):
        mock_state = MagicMock()
        with patch("features.ws.router.state", mock_state), \
             patch("features.ws.router.broadcast_state", new_callable=AsyncMock) as mock_broadcast:
            await _handle_score_award({"participant_id": "uuid1", "points": 200})
        mock_state.add_score.assert_called_once_with("uuid1", 200)
        mock_broadcast.assert_called_once()
