"""Step definitions for attention_bell.feature.

These bind the Gherkin to the REAL daemon attention router (host + participant)
and the REAL ``participant_state`` singleton — the same harness as
``tests/daemon/test_attention_gate.py``, ``test_attention_hardening.py`` and
``test_bell_router.py`` — driven in-process via Starlette TestClient. The overlay
bridge and host WebSocket are captured with mocks. No browser, no docker.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from pytest_bdd import given, parsers, scenarios, then, when
from starlette.testclient import TestClient

from daemon.attention.router import (
    HOST_NOTIFICATION_MAX_LEN,
    BELL_RATE_LIMIT,
    bell_rate_limiter,
    host_router,
    participant_router,
)
from daemon.participant.state import ParticipantState, participant_state
from daemon.ws_messages import BellRungMsg

scenarios("../attention_bell.feature")


@pytest.fixture(autouse=True)
def bdd():
    """Fresh attention state + captured overlay/host/broadcast sinks per scenario.

    Autouse so the state reset below always runs BEFORE the first Given step —
    otherwise a lazily-initialized fixture would clobber "Given attention is
    enabled" when the When step first requests it.
    """
    participant_state.attention_enabled = False
    participant_state.participant_names.clear()
    participant_state.anonymous_pids.clear()
    bell_rate_limiter.reset()

    app = FastAPI()
    app.include_router(host_router)
    app.include_router(participant_router)

    import daemon.addon_bridge_client  # ensure module is importable before patching

    with patch("daemon.attention.router.notify_host", new_callable=AsyncMock) as mock_host, \
         patch("daemon.addon_bridge_client.send_bell", return_value=True) as mock_send_bell, \
         patch("daemon.attention.router.broadcast") as mock_broadcast, \
         patch("daemon.misc.content_files.get_active_session_folder", return_value=None):
        yield {
            "client": TestClient(app),
            "host": mock_host,
            "send_bell": mock_send_bell,
            "broadcast": mock_broadcast,
        }

    participant_state.attention_enabled = False
    participant_state.participant_names.clear()
    participant_state.anonymous_pids.clear()
    bell_rate_limiter.reset()


def _ring(bdd, pid):
    return bdd["client"].post(
        "/api/participant/bell", headers={"X-Participant-ID": pid}
    )


def _notify(bdd, text):
    return bdd["client"].post(
        "/api/sid1/host/attention/notify", json={"text": text}
    )


# ── Enable-gate defaults ────────────────────────────────────────────────────


@given("a brand-new participant state")
def _brand_new_state(bdd):
    bdd["fresh"] = ParticipantState()


@then("the attention capability is disabled by default")
def _disabled_by_default(bdd):
    assert bdd["fresh"].attention_enabled is False


@when("the attention capability is turned on and the session is reset")
def _turn_on_then_reset(bdd):
    ps = bdd["fresh"]
    ps.attention_enabled = True
    ps.reset()


@then("the attention capability is disabled again")
def _disabled_again(bdd):
    assert bdd["fresh"].attention_enabled is False


# ── Given: gate state + participant identity ────────────────────────────────


@given("attention is disabled")
def _attention_off():
    participant_state.attention_enabled = False


@given("attention is enabled")
def _attention_on():
    participant_state.attention_enabled = True


@given(parsers.parse('participant "{pid}" is known as "{name}"'))
def _known_as(pid, name):
    participant_state.participant_names[pid] = name


@given(parsers.parse('participant "{pid}" joined anonymously'))
def _joined_anon(pid):
    participant_state.anonymous_pids.add(pid)


# ── When: ring / notify actions ─────────────────────────────────────────────


@when(parsers.parse('participant "{pid}" rings the bell'))
@when(parsers.parse('unknown participant "{pid}" rings the bell'))
def _ring_bell(bdd, pid):
    bdd["ring_resp"] = _ring(bdd, pid)


@when(parsers.parse('the host broadcasts the notification "{text}"'))
def _host_broadcasts(bdd, text):
    bdd["notify_resp"] = _notify(bdd, text)


@when("the host broadcasts an over-length notification")
def _host_broadcasts_overlong(bdd):
    bdd["notify_resp"] = _notify(bdd, "x" * (HOST_NOTIFICATION_MAX_LEN + 200_000))


@when(parsers.parse('a crafted "{pid}" id rings the bell up to the limit'))
def _ring_up_to_limit(bdd, pid):
    bdd["ring_codes"] = [_ring(bdd, pid).status_code for _ in range(BELL_RATE_LIMIT)]
    bdd["overflow_resp"] = _ring(bdd, pid)


# ── Then: OFF-path assertions ───────────────────────────────────────────────


@then("the ring is accepted as a no-op")
def _ring_noop(bdd):
    assert bdd["ring_resp"].status_code == 204


@then("nothing is forwarded to the overlay")
def _nothing_to_overlay(bdd):
    bdd["send_bell"].assert_not_called()


@then("nothing is forwarded to the host")
def _nothing_to_host(bdd):
    bdd["host"].assert_not_called()


@then("the host notification is refused")
def _notify_refused(bdd):
    # Defense-in-depth: the daemon refuses to broadcast while the gate is OFF.
    assert bdd["notify_resp"].status_code == 409


@then("nothing is broadcast to participants")
def _nothing_broadcast(bdd):
    bdd["broadcast"].assert_not_called()


# ── Then: ON-path forwarding ────────────────────────────────────────────────


@then(parsers.parse('the overlay is notified that "{caller}" rang the bell'))
def _overlay_notified(bdd, caller):
    bdd["send_bell"].assert_called_once_with(caller, False)


@then(parsers.parse('the host is notified that "{caller}" rang the bell'))
def _host_notified(bdd, caller):
    bdd["host"].assert_called_once()
    sent = bdd["host"].call_args[0][0]
    assert isinstance(sent, BellRungMsg)
    assert sent.model_dump() == {"type": "bell_rung", "caller": caller, "anonymous": False}


@then("the host notification carries no UUID")
def _host_no_uuid(bdd):
    payload = bdd["host"].call_args[0][0].model_dump()
    assert set(payload.keys()) == {"type", "caller", "anonymous"}


@then(parsers.parse('the overlay ring for "{caller}" is flagged anonymous'))
def _overlay_anon(bdd, caller):
    bdd["send_bell"].assert_called_once_with(caller, True)


@then(parsers.parse('the host ring for "{caller}" is flagged anonymous'))
def _host_anon(bdd, caller):
    sent = bdd["host"].call_args[0][0]
    assert sent.model_dump() == {"type": "bell_rung", "caller": caller, "anonymous": True}


# ── Then: host-notification broadcast ───────────────────────────────────────


@then("the host notification is accepted")
def _notify_accepted(bdd):
    assert bdd["notify_resp"].status_code == 204


@then("the notification is broadcast to participants")
def _notify_broadcast(bdd):
    bdd["broadcast"].assert_called_once()


@then("the host notification is rejected as invalid")
def _notify_rejected(bdd):
    # Pydantic max_length rejects the over-length body before it is broadcast.
    assert bdd["notify_resp"].status_code == 422


# ── Then: rate-limit bypass defense ─────────────────────────────────────────


@then("every ring up to the limit is accepted")
def _all_accepted(bdd):
    assert bdd["ring_codes"] == [204] * BELL_RATE_LIMIT


@then("the next ring is throttled")
def _next_throttled(bdd):
    assert bdd["overflow_resp"].status_code == 429
