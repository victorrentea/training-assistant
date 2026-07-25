"""Attention hardening tests: host-notification length cap (fix #9) and
per-session rate-limiter reset (fix #10)."""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.attention.router import (
    HOST_NOTIFICATION_MAX_LEN,
    host_router,
    participant_router,
)
from daemon.participant.state import participant_state


# ── Fix #9: host-notification length cap ──────────────────────────────────────

@pytest.fixture
def notify_client():
    app = FastAPI()
    app.include_router(host_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def enable_attention_and_stub_sinks():
    participant_state.attention_enabled = True
    with patch("daemon.attention.router.broadcast"), \
         patch("daemon.misc.content_files.get_active_session_folder", return_value=None):
        yield
    participant_state.attention_enabled = False


class TestHostNotificationLengthCap:
    def test_normal_text_accepted(self, notify_client):
        r = notify_client.post("/api/sid1/host/attention/notify", json={"text": "Break in 5 min"})
        assert r.status_code == 204

    def test_max_length_text_accepted(self, notify_client):
        r = notify_client.post(
            "/api/sid1/host/attention/notify",
            json={"text": "x" * HOST_NOTIFICATION_MAX_LEN},
        )
        assert r.status_code == 204

    def test_over_length_text_rejected(self, notify_client):
        # A 200KB body must not be broadcast to everyone — rejected at validation.
        r = notify_client.post(
            "/api/sid1/host/attention/notify",
            json={"text": "x" * 200_000},
        )
        assert r.status_code == 422

    def test_one_over_cap_rejected(self, notify_client):
        r = notify_client.post(
            "/api/sid1/host/attention/notify",
            json={"text": "x" * (HOST_NOTIFICATION_MAX_LEN + 1)},
        )
        assert r.status_code == 422

    def test_over_length_is_not_broadcast(self, notify_client):
        with patch("daemon.attention.router.broadcast") as mock_bcast:
            notify_client.post(
                "/api/sid1/host/attention/notify",
                json={"text": "x" * 200_000},
            )
            mock_bcast.assert_not_called()


# ── Fix #10: rate limiters cleared on session reset ───────────────────────────

class TestLimiterResetPerSession:
    def test_bell_limiter_reset_lets_returning_uuid_ring_again(self):
        from daemon.attention.router import BELL_RATE_LIMIT, bell_rate_limiter

        app = FastAPI()
        app.include_router(participant_router)
        client = TestClient(app)

        bell_rate_limiter.reset()
        participant_state.attention_enabled = True
        try:
            with patch("daemon.attention.router.notify_host", new_callable=AsyncMock), \
                 patch("daemon.addon_bridge_client.send_bell", return_value=True):
                # Exhaust the limit for this UUID.
                for _ in range(BELL_RATE_LIMIT):
                    assert client.post(
                        "/api/participant/bell", headers={"X-Participant-ID": "returning"}
                    ).status_code == 204
                assert client.post(
                    "/api/participant/bell", headers={"X-Participant-ID": "returning"}
                ).status_code == 429

                # Fresh session: reset() must clear the stale hits…
                participant_state.reset()
                participant_state.attention_enabled = True  # reset forces it OFF

                # …so the same UUID is NOT throttled in the new session.
                assert client.post(
                    "/api/participant/bell", headers={"X-Participant-ID": "returning"}
                ).status_code == 204
        finally:
            bell_rate_limiter.reset()
            participant_state.attention_enabled = False

    def test_emoji_limiter_also_reset_on_session_reset(self):
        from daemon.emoji.router import (
            EMOJI_RATE_LIMIT,
            emoji_rate_limiter,
            participant_router as emoji_participant_router,
        )

        app = FastAPI()
        app.include_router(emoji_participant_router)
        client = TestClient(app)

        emoji_rate_limiter.reset()
        participant_state.emoji_global_enabled = True
        try:
            with patch("daemon.emoji.router.notify_host", new_callable=AsyncMock), \
                 patch("daemon.addon_bridge_client.send_emoji", return_value=True):
                for _ in range(EMOJI_RATE_LIMIT):
                    assert client.post(
                        "/api/participant/emoji/reaction",
                        json={"emoji": "❤️"},
                        headers={"X-Participant-ID": "returning"},
                    ).status_code == 204
                assert client.post(
                    "/api/participant/emoji/reaction",
                    json={"emoji": "❤️"},
                    headers={"X-Participant-ID": "returning"},
                ).status_code == 429

                participant_state.reset()
                participant_state.emoji_global_enabled = True

                assert client.post(
                    "/api/participant/emoji/reaction",
                    json={"emoji": "❤️"},
                    headers={"X-Participant-ID": "returning"},
                ).status_code == 204
        finally:
            emoji_rate_limiter.reset()
