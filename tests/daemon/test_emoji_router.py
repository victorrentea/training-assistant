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


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """The emoji rate limiter is module-global — clear it between tests."""
    from daemon.emoji.router import emoji_rate_limiter
    emoji_rate_limiter.reset()
    yield
    emoji_rate_limiter.reset()


class TestEmojiReaction:
    def test_valid_emoji(self, emoji_client):
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "❤️"},
                                  headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 204
        assert resp.content == b""

    def test_missing_participant_id(self, emoji_client):
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "❤️"})
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

    def test_non_whitelisted_emoji_rejected(self, emoji_client):
        """A valid short emoji that the UI does not offer must be rejected.

        This is the pentest guard: only catalog emoji may float on the host
        and the macOS overlay.
        """
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "🎉"},
                                  headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 400

    def test_bridge_down_does_not_break(self, emoji_client, mock_externals):
        """Addon bridge not running — best-effort, should not fail."""
        mock_externals["send_emoji"].return_value = False
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "❤️"},
                                  headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 204
        assert resp.content == b""

    def test_sends_to_host_ws(self, emoji_client, mock_externals):
        from daemon.ws_messages import EmojiReactionMsg
        emoji_client.post("/api/participant/emoji/reaction",
                           json={"emoji": "❤️"},
                           headers={"X-Participant-ID": "uuid1"})
        mock_externals["host"].assert_called_once()
        call_msg = mock_externals["host"].call_args[0][0]
        assert isinstance(call_msg, EmojiReactionMsg)
        assert call_msg.model_dump()["type"] == "emoji_reaction"
        assert call_msg.model_dump()["emoji"] == "❤️"

    def test_sends_emoji_to_bridge(self, emoji_client, mock_externals):
        emoji_client.post("/api/participant/emoji/reaction",
                           json={"emoji": "❤️"},
                           headers={"X-Participant-ID": "uuid1"})
        mock_externals["send_emoji"].assert_called_once_with("❤️")

    def test_rate_limit_blocks_sixteenth_per_minute(self, emoji_client):
        """A burst of 15 is allowed; the 16th within the minute is throttled."""
        for _ in range(15):
            resp = emoji_client.post("/api/participant/emoji/reaction",
                                      json={"emoji": "❤️"},
                                      headers={"X-Participant-ID": "burst-uuid"})
            assert resp.status_code == 204
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "❤️"},
                                  headers={"X-Participant-ID": "burst-uuid"})
        assert resp.status_code == 429

    def test_rate_limit_is_per_participant(self, emoji_client):
        """One participant hitting the limit does not throttle another."""
        for _ in range(15):
            emoji_client.post("/api/participant/emoji/reaction",
                              json={"emoji": "❤️"},
                              headers={"X-Participant-ID": "p1"})
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "❤️"},
                                  headers={"X-Participant-ID": "p2"})
        assert resp.status_code == 204

    def test_host_is_exempt_from_rate_limit(self, emoji_client):
        """Host reactions (__host__) are never throttled."""
        for _ in range(20):
            resp = emoji_client.post("/api/participant/emoji/reaction",
                                      json={"emoji": "❤️"},
                                      headers={"X-Participant-ID": "__host__"})
            assert resp.status_code == 204
