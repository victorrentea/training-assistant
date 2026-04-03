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
    """Mock send_to_host and httpx for all emoji tests."""
    with patch("daemon.emoji.router.send_to_host", new_callable=AsyncMock) as mock_host, \
         patch("daemon.emoji.router.httpx") as mock_httpx:
        mock_client = AsyncMock()
        mock_httpx.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_httpx.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
        yield {"host": mock_host, "httpx_client": mock_client}


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

    def test_overlay_failure_does_not_break(self, emoji_client, mock_externals):
        """Overlay at localhost:56789 not running — should not fail."""
        mock_externals["httpx_client"].post.side_effect = Exception("Connection refused")
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "❤️"},
                                  headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 200

    def test_sends_to_host_ws(self, emoji_client, mock_externals):
        emoji_client.post("/api/participant/emoji/reaction",
                           json={"emoji": "🎉"},
                           headers={"X-Participant-ID": "uuid1"})
        mock_externals["host"].assert_called_once()
        call_msg = mock_externals["host"].call_args[0][0]
        assert call_msg["type"] == "emoji_reaction"
        assert call_msg["emoji"] == "🎉"
