"""Tests for daemon emoji router."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from starlette.testclient import TestClient
from fastapi import FastAPI

from daemon.emoji.router import EMOJI_RATE_LIMIT, host_router, participant_router
from daemon.participant.state import participant_state


@pytest.fixture
def emoji_client():
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture
def emoji_full_client():
    """Client with both participant and host (toggle) routers mounted."""
    app = FastAPI()
    app.include_router(participant_router)
    app.include_router(host_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_emoji_global_state():
    """The master switch + counters live on the participant_state singleton."""
    participant_state.emoji_global_enabled = True
    participant_state.emoji_counters.clear()
    participant_state.mode = "workshop"
    yield
    participant_state.emoji_global_enabled = True
    participant_state.emoji_counters.clear()
    participant_state.mode = "workshop"


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
        from daemon.emoji.glow import color_for_participant
        emoji_client.post("/api/participant/emoji/reaction",
                           json={"emoji": "❤️"},
                           headers={"X-Participant-ID": "uuid1"})
        mock_externals["send_emoji"].assert_called_once_with("❤️", color_for_participant("uuid1"))

    def test_rate_limit_blocks_one_past_the_limit_per_minute(self, emoji_client):
        """A burst up to EMOJI_RATE_LIMIT is allowed; the next one within the minute is throttled."""
        for _ in range(EMOJI_RATE_LIMIT):
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
        for _ in range(EMOJI_RATE_LIMIT):
            emoji_client.post("/api/participant/emoji/reaction",
                              json={"emoji": "❤️"},
                              headers={"X-Participant-ID": "p1"})
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "❤️"},
                                  headers={"X-Participant-ID": "p2"})
        assert resp.status_code == 204

    def test_host_is_exempt_from_rate_limit(self, emoji_client):
        """Host reactions (__host__) are never throttled."""
        for _ in range(EMOJI_RATE_LIMIT + 5):
            resp = emoji_client.post("/api/participant/emoji/reaction",
                                      json={"emoji": "❤️"},
                                      headers={"X-Participant-ID": "__host__"})
            assert resp.status_code == 204

    def test_host_id_through_railway_is_rate_limited(self, emoji_client):
        """SECURITY: the "__host__" exemption is for the host's own local calls. A
        participant typing X-Participant-ID: __host__ arrives through Railway (proxy
        marker set) and is throttled like anyone else."""
        headers = {"X-Participant-ID": "__host__", "x-railway-proxied": "1"}
        for _ in range(EMOJI_RATE_LIMIT):
            r = emoji_client.post("/api/participant/emoji/reaction", json={"emoji": "❤️"}, headers=headers)
            assert r.status_code == 204
        r = emoji_client.post("/api/participant/emoji/reaction", json={"emoji": "❤️"}, headers=headers)
        assert r.status_code == 429

    def test_no_rate_limit_exemption_for_crafted_host_prefix(self, emoji_client):
        """SECURITY (fix #5): only the exact "__host__" id is exempt.

        A crafted "__"-prefixed X-Participant-ID (e.g. "__x") used to bypass the
        limit via the old startswith("__") check — it must now be throttled like
        any other participant.
        """
        for _ in range(EMOJI_RATE_LIMIT):
            r = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "❤️"},
                                  headers={"X-Participant-ID": "__x"})
            assert r.status_code == 204
        r = emoji_client.post("/api/participant/emoji/reaction",
                              json={"emoji": "❤️"},
                              headers={"X-Participant-ID": "__x"})
        assert r.status_code == 429


class TestEmojiMasterSwitch:
    def test_disabled_drops_silently_without_forwarding(self, emoji_client, mock_externals):
        """When the master switch is off, the reaction is accepted (204) but
        never forwarded to the host screen or the desktop overlay."""
        participant_state.emoji_global_enabled = False
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "❤️"},
                                  headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 204
        assert resp.content == b""
        mock_externals["host"].assert_not_called()
        mock_externals["send_emoji"].assert_not_called()

    def test_disabled_does_not_bump_counters_in_talk_mode(self, emoji_client):
        """A dropped reaction must not advance the cumulative talk-mode counter."""
        participant_state.mode = "talk"
        participant_state.emoji_global_enabled = False
        emoji_client.post("/api/participant/emoji/reaction",
                          json={"emoji": "❤️"},
                          headers={"X-Participant-ID": "uuid1"})
        assert participant_state.emoji_counters.get("❤️", 0) == 0

    def test_enabled_forwards_normally(self, emoji_client, mock_externals):
        """With the switch on (default), forwarding happens as before."""
        participant_state.emoji_global_enabled = True
        resp = emoji_client.post("/api/participant/emoji/reaction",
                                  json={"emoji": "❤️"},
                                  headers={"X-Participant-ID": "uuid1"})
        assert resp.status_code == 204
        mock_externals["host"].assert_called_once()
        from daemon.emoji.glow import color_for_participant
        mock_externals["send_emoji"].assert_called_once_with("❤️", color_for_participant("uuid1"))

    def test_toggle_endpoint_flips_and_reports(self, emoji_full_client):
        """POST /global-toggle flips the flag and returns the new value."""
        with patch("daemon.misc.content_files.get_active_session_folder", return_value=None):
            r1 = emoji_full_client.post("/api/sid1/host/emoji/global-toggle")
            assert r1.status_code == 200
            assert r1.json() == {"emoji_global_enabled": False}
            assert participant_state.emoji_global_enabled is False

            r2 = emoji_full_client.post("/api/sid1/host/emoji/global-toggle")
            assert r2.json() == {"emoji_global_enabled": True}
            assert participant_state.emoji_global_enabled is True

    def test_flag_persists_through_snapshot_restore(self):
        """The flag round-trips via snapshot() -> sync_from_restore()."""
        participant_state.emoji_global_enabled = False
        snap = participant_state.snapshot()
        assert snap["emoji_global_enabled"] is False

        participant_state.emoji_global_enabled = True  # simulate a fresh process
        participant_state.sync_from_restore(snap)
        assert participant_state.emoji_global_enabled is False


class TestEmojiGlobalCap:
    """A leaked session link must not let anyone flood the projected screen by
    rotating X-Participant-ID past the per-participant limit."""

    @pytest.fixture
    def tiny_bucket(self, monkeypatch):
        from daemon.emoji import router as emoji_router
        from daemon.emoji.rate_limit import TokenBucket
        bucket = TokenBucket(burst=3, rate_per_s=0.001)
        monkeypatch.setattr(emoji_router, "emoji_global_bucket", bucket)
        return bucket

    def _react(self, client, pid):
        return client.post("/api/participant/emoji/reaction",
                           json={"emoji": "❤️"},
                           headers={"X-Participant-ID": pid})

    def test_rotating_ids_are_capped_silently(self, emoji_client, mock_externals, tiny_bucket):
        statuses = [self._react(emoji_client, f"rotating-{i}").status_code for i in range(10)]
        assert statuses == [204] * 10  # indistinguishable from success
        assert mock_externals["send_emoji"].call_count == 3
        assert mock_externals["host"].call_count == 3

    def test_capped_reactions_do_not_bump_talk_counters(self, emoji_client, tiny_bucket):
        participant_state.mode = "talk"
        with patch("daemon.emoji.router._emoji_throttle"):
            for i in range(10):
                self._react(emoji_client, f"rotating-{i}")
        assert participant_state.emoji_counters.get("❤️", 0) == 3

    def test_capped_reactions_log_at_most_one_line(self, emoji_client, tiny_bucket):
        with patch("daemon.emoji.router.daemon_log") as dlog, \
             patch("daemon.emoji.router._global_drop_logged_at", float("-inf")):
            for i in range(10):
                self._react(emoji_client, f"rotating-{i}")
        lines = [c.args[1] for c in dlog.info.call_args_list]
        assert sum("reacted" in line for line in lines) == 3  # the allowed ones
        assert sum("global cap" in line for line in lines) == 1  # 7 drops, one line

    def test_per_participant_429_does_not_drain_the_global_budget(
        self, emoji_client, monkeypatch
    ):
        from daemon.emoji import router as emoji_router
        from daemon.emoji.rate_limit import TokenBucket
        bucket = TokenBucket(burst=EMOJI_RATE_LIMIT + 1, rate_per_s=0.001)
        monkeypatch.setattr(emoji_router, "emoji_global_bucket", bucket)
        for _ in range(EMOJI_RATE_LIMIT):
            assert self._react(emoji_client, "masher").status_code == 204
        for _ in range(10):
            assert self._react(emoji_client, "masher").status_code == 429
        # The masher's 429s did not eat the last shared token.
        assert self._react(emoji_client, "someone-else").status_code == 204
        assert bucket.allow() is False

    def test_env_parsing_falls_back_to_the_default(self, monkeypatch):
        from daemon.emoji import router as emoji_router
        monkeypatch.setenv("EMOJI_TEST_VALUE", "12.5")
        assert emoji_router._env_float("EMOJI_TEST_VALUE", 1.0) == 12.5
        for bad in ("", "abc", "0", "-3"):
            monkeypatch.setenv("EMOJI_TEST_VALUE", bad)
            assert emoji_router._env_float("EMOJI_TEST_VALUE", 1.0) == 1.0
