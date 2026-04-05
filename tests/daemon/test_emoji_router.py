"""Tests for daemon emoji router."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from starlette.testclient import TestClient
from fastapi import FastAPI

from daemon.emoji.router import participant_router


@pytest.fixture
def emoji_client():
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_externals():
    """Mock notify_host and addon_bridge_client for all emoji tests."""
    import daemon.addon_bridge_client  # ensure module is loaded before patching
    with patch("daemon.emoji.router.notify_host", new_callable=AsyncMock) as mock_host, \
         patch("daemon.addon_bridge_client.send_emoji", return_value=True) as mock_send_emoji:
        yield {"host": mock_host, "send_emoji": mock_send_emoji}


class TestEmojiReaction:
    def test_valid_emoji(self, emoji_client):
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "🎉"},
                                  headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200

    def test_missing_participant_id(self, emoji_client):
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "🎉"})
        assert resp.status_code == 400

    def test_empty_emoji_rejected(self, emoji_client):
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": ""},
                                  headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400

    def test_long_emoji_rejected(self, emoji_client):
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "12345"},
                                  headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400

    def test_bridge_down_does_not_break(self, emoji_client, mock_externals):
        """Addon bridge not running — best-effort, should not fail."""
        mock_externals["send_emoji"].return_value = False
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "❤️"},
                                  headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200

    def test_sends_to_host_ws(self, emoji_client, mock_externals):
        from daemon.ws_messages import EmojiReactionMsg
        emoji_client.post("/api/participant/emoji/reaction",
                           json={"emoji": "🎉"},
                           headers={"X-Participant-ID": "uuid1"})
        mock_externals["host"].assert_called_once()
        call_msg = mock_externals["host"].call_args[0][0]
        assert isinstance(call_msg, EmojiReactionMsg)
        assert call_msg.model_dump()["type"] == "emoji_reaction"
        assert call_msg.model_dump()["emoji"] == "🎉"

    def test_sends_emoji_to_bridge(self, emoji_client, mock_externals):
        emoji_client.post("/api/participant/emoji/reaction",
                           json={"emoji": "🎉"},
                           headers={"X-Participant-ID": "uuid1"})
        mock_externals["send_emoji"].assert_called_once_with("🎉")
