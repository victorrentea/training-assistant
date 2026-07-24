"""Tests for the attention-bell router (Direction B: participant → host).

Covers the enable-gate (defense in depth), name resolution + logging, the exact
`bell_ring` wire contract sent to the overlay, the missing-header 400, the
server-side rate limit 429, graceful degradation when the bridge is down, the
optional host dual-render, and the no-UUID guarantee on every emitted payload.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from starlette.testclient import TestClient
from fastapi import FastAPI

from daemon.attention.router import participant_router
from daemon.participant.state import participant_state
from daemon.ws_messages import BellRungMsg


@pytest.fixture
def bell_client():
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    participant_state.attention_enabled = True  # most tests exercise the ON path
    participant_state.participant_names.clear()
    yield
    participant_state.attention_enabled = False
    participant_state.participant_names.clear()


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    from daemon.attention.router import bell_rate_limiter
    bell_rate_limiter.reset()
    yield
    bell_rate_limiter.reset()


@pytest.fixture(autouse=True)
def mock_externals():
    import daemon.addon_bridge_client  # ensure loaded before patching
    with patch("daemon.attention.router.notify_host", new_callable=AsyncMock) as mock_host, \
         patch("daemon.addon_bridge_client.send_bell", return_value=True) as mock_send_bell:
        yield {"host": mock_host, "send_bell": mock_send_bell}


class TestGate:
    def test_disabled_is_noop(self, bell_client, mock_externals):
        """Defense in depth: with the gate OFF a direct POST does nothing."""
        participant_state.attention_enabled = False
        participant_state.participant_names["u1"] = "Alice"
        resp = bell_client.post("/api/participant/bell", headers={"X-Participant-ID": "u1"})
        assert resp.status_code == 204
        mock_externals["send_bell"].assert_not_called()
        mock_externals["host"].assert_not_called()

    def test_enabled_forwards(self, bell_client, mock_externals):
        participant_state.participant_names["u1"] = "Alice"
        resp = bell_client.post("/api/participant/bell", headers={"X-Participant-ID": "u1"})
        assert resp.status_code == 204
        mock_externals["send_bell"].assert_called_once_with("Alice")


class TestResolveLogForward:
    def test_resolves_name_and_sends_exact_contract(self, bell_client, mock_externals):
        participant_state.participant_names["u1"] = "Alice"
        bell_client.post("/api/participant/bell", headers={"X-Participant-ID": "u1"})
        mock_externals["send_bell"].assert_called_once_with("Alice")

    def test_unknown_pid_falls_back_to_pid(self, bell_client, mock_externals):
        """No name known → caller resolves to the pid (never crashes)."""
        bell_client.post("/api/participant/bell", headers={"X-Participant-ID": "u-unknown"})
        mock_externals["send_bell"].assert_called_once_with("u-unknown")

    def test_logs_the_caller(self, bell_client, mock_externals):
        participant_state.participant_names["u1"] = "Alice"
        with patch("daemon.attention.router.daemon_log.info") as mock_log:
            bell_client.post("/api/participant/bell", headers={"X-Participant-ID": "u1"})
        logged = " ".join(str(c.args) for c in mock_log.call_args_list)
        assert "rang the bell" in logged and "Alice" in logged

    def test_bell_ring_wire_shape_matches_swift_contract(self):
        """The overlay expects EXACTLY {"type":"bell_ring","caller":<name>}.

        Assert the AddonBridgeClient serialises precisely that — no extra keys,
        no UUID — since the merged Swift receiver parses it verbatim.
        """
        from daemon.addon_bridge_client import AddonBridgeClient
        client = AddonBridgeClient()
        captured = {}
        with patch.object(client, "_send", side_effect=lambda m: captured.update({"msg": m}) or True):
            client.send_bell("Alice")
        assert captured["msg"] == {"type": "bell_ring", "caller": "Alice"}


class TestErrorsAndLimits:
    def test_missing_participant_id_is_400(self, bell_client, mock_externals):
        resp = bell_client.post("/api/participant/bell")
        assert resp.status_code == 400
        mock_externals["send_bell"].assert_not_called()

    def test_rate_limit_blocks_excess(self, bell_client, mock_externals):
        from daemon.attention.router import BELL_RATE_LIMIT
        for _ in range(BELL_RATE_LIMIT):
            r = bell_client.post("/api/participant/bell", headers={"X-Participant-ID": "spammer"})
            assert r.status_code == 204
        r = bell_client.post("/api/participant/bell", headers={"X-Participant-ID": "spammer"})
        assert r.status_code == 429

    def test_no_rate_limit_exemption_for_crafted_host_prefix(self, bell_client, mock_externals):
        """SECURITY: a crafted '__'-prefixed X-Participant-ID gets NO exemption.

        The host page has no bell control, so unlike emoji there is no
        legitimate '__host__' caller — an id-prefix exemption would just be a
        rate-limit bypass for anyone who edits the header.
        """
        from daemon.attention.router import BELL_RATE_LIMIT
        for _ in range(BELL_RATE_LIMIT):
            r = bell_client.post("/api/participant/bell", headers={"X-Participant-ID": "__host__"})
            assert r.status_code == 204
        r = bell_client.post("/api/participant/bell", headers={"X-Participant-ID": "__host__"})
        assert r.status_code == 429

    def test_bridge_down_still_204(self, bell_client, mock_externals):
        """Overlay disconnected → log the drop, still return success."""
        mock_externals["send_bell"].return_value = False
        participant_state.participant_names["u1"] = "Alice"
        resp = bell_client.post("/api/participant/bell", headers={"X-Participant-ID": "u1"})
        assert resp.status_code == 204


class TestHostDualRender:
    def test_notifies_host_with_caller_no_uuid(self, bell_client, mock_externals):
        participant_state.participant_names["u1"] = "Alice"
        bell_client.post("/api/participant/bell", headers={"X-Participant-ID": "u1"})
        mock_externals["host"].assert_called_once()
        sent = mock_externals["host"].call_args[0][0]
        assert isinstance(sent, BellRungMsg)
        assert sent.model_dump() == {"type": "bell_rung", "caller": "Alice"}
