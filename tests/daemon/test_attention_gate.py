"""Tests for the attention master enable-gate (`attention_enabled`).

Covers: default OFF at construction, reset OFF on a fresh session, snapshot/
restore round-trip, the host toggle endpoint (flip + persist + live broadcast),
and the flag surfacing in host + participant state payloads. Mirrors the emoji
master-switch tests but asserts the OFF-by-default + broadcast differences.
"""
import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
from fastapi import FastAPI

from daemon.attention.router import host_router
from daemon.participant.state import ParticipantState, participant_state
from daemon.ws_messages import AttentionEnabledMsg


@pytest.fixture(autouse=True)
def reset_attention_state():
    participant_state.attention_enabled = False
    yield
    participant_state.attention_enabled = False


@pytest.fixture
def attention_client():
    app = FastAPI()
    app.include_router(host_router)
    return TestClient(app)


class TestDefaultsAndReset:
    def test_fresh_state_starts_disabled(self):
        """A brand-new ParticipantState has attention OFF."""
        assert ParticipantState().attention_enabled is False

    def test_reset_returns_gate_to_off(self):
        """reset() (fresh-session path) forces attention back OFF."""
        ps = ParticipantState()
        ps.attention_enabled = True
        ps.reset()
        assert ps.attention_enabled is False

    def test_snapshot_restore_round_trip(self):
        """The flag is carried through snapshot() -> sync_from_restore()."""
        ps = ParticipantState()
        ps.attention_enabled = True
        snap = ps.snapshot()
        assert snap["attention_enabled"] is True

        fresh = ParticipantState()
        fresh.sync_from_restore(snap)
        assert fresh.attention_enabled is True

    def test_restore_omitting_flag_keeps_safe_default(self):
        """A restore payload without the flag leaves it at the OFF default."""
        ps = ParticipantState()
        assert ps.attention_enabled is False
        ps.sync_from_restore({"mode": "workshop"})  # no attention_enabled key
        assert ps.attention_enabled is False


class TestToggleEndpoint:
    def test_toggle_flips_persists_and_broadcasts(self, attention_client):
        with patch("daemon.misc.content_files.get_active_session_folder", return_value=None), \
             patch("daemon.attention.router.broadcast") as mock_bcast:
            r1 = attention_client.post("/api/sid1/host/attention/global-toggle")
            assert r1.status_code == 200
            assert r1.json() == {"attention_enabled": True}
            assert participant_state.attention_enabled is True

            # Live broadcast fired with the typed message.
            mock_bcast.assert_called_once()
            sent = mock_bcast.call_args[0][0]
            assert isinstance(sent, AttentionEnabledMsg)
            assert sent.model_dump() == {"type": "attention_enabled", "enabled": True}

            mock_bcast.reset_mock()
            r2 = attention_client.post("/api/sid1/host/attention/global-toggle")
            assert r2.json() == {"attention_enabled": False}
            assert participant_state.attention_enabled is False
            sent2 = mock_bcast.call_args[0][0]
            assert sent2.model_dump() == {"type": "attention_enabled", "enabled": False}

    def test_broadcast_payload_has_no_uuid(self, attention_client):
        """SECURITY: the attention_enabled frame carries a boolean only."""
        with patch("daemon.misc.content_files.get_active_session_folder", return_value=None), \
             patch("daemon.attention.router.broadcast") as mock_bcast:
            attention_client.post("/api/sid1/host/attention/global-toggle")
            payload = mock_bcast.call_args[0][0].model_dump()
            assert set(payload.keys()) == {"type", "enabled"}


class TestStateSurfacing:
    def test_flag_in_participant_state_payload(self):
        from daemon.participant.router import ParticipantStateResponse
        assert "attention_enabled" in ParticipantStateResponse.model_fields

    def test_flag_in_host_state_payload(self):
        from daemon.host_state_router import HostStateResponse
        assert "attention_enabled" in HostStateResponse.model_fields
