"""Step definitions for session_hijack.feature.

These bind the Gherkin to the REAL ``railway.app:app`` ASGI app (Starlette
TestClient for HTTP + WebSocket) and the REAL ws-router ``_handle_set_session_id``
handler — the same harness as ``tests/test_gateway_hardening.py``. The daemon and
browser are simulated with in-process sockets; nothing leaves the process.
"""
import asyncio
import json
import os
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from railway.app import app
from railway.features.ws import router as ws_router
from railway.features.ws.router import _INVALID_REDIRECT, _handle_set_session_id
from railway.shared.rate_limit import probe_limiter
from railway.shared.state import state

scenarios("../session_hijack.feature")


# ── Harness fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def bdd():
    """Clean gateway singleton + full rate-limit budget per scenario.

    Rate limiting is disabled for the duration of the scenario so the page/probe
    assertions are deterministic; the original env value is restored on teardown
    so nothing leaks into the rest of the suite.
    """
    state.reset()
    probe_limiter.reset()
    _prev_env = os.environ.get("GATEWAY_RATE_LIMIT_DISABLED")
    ctx = {}
    try:
        yield ctx
    finally:
        ws_router._cancel_pending_kick()
        state.reset()
        probe_limiter.reset()
        if _prev_env is None:
            os.environ.pop("GATEWAY_RATE_LIMIT_DISABLED", None)
        else:
            os.environ["GATEWAY_RATE_LIMIT_DISABLED"] = _prev_env


def _populate_session_caches() -> None:
    state.slides = [{"slug": "intro"}]
    state.slides_updated = {"intro": {"status": "cached"}}
    state.uploaded_files = {"u1": [{"id": 0, "filename": "a.pdf"}]}
    state.upload_next_id = 7
    state.participant_history = {"u1"}
    state.participant_ips = {"u1": "1.2.3.4"}
    state.participant_names = {"u1": "Alice"}
    state.participant_avatars = {"u1": "avatar"}


def _caches_cleared() -> bool:
    return (
        state.slides == []
        and state.slides_updated == {}
        and state.uploaded_files == {}
        and state.upload_next_id == 0
        and state.participant_history == set()
        and state.participant_ips == {}
        and state.participant_names == {}
        and state.participant_avatars == {}
    )


# ── Background ──────────────────────────────────────────────────────────────


@given("a clean gateway with rate limiting disabled")
def _clean_gateway(bdd):
    os.environ["GATEWAY_RATE_LIMIT_DISABLED"] = "1"
    bdd["client"] = TestClient(app)


# ── Given: active session states ────────────────────────────────────────────


@given(parsers.parse('the active session is "{sid}"'))
def _active_session(bdd, sid):
    state.session_id = sid
    state.session_type = "workshop"
    state.daemon_ws = object()  # a connected daemon


@given(parsers.parse('the active session is "{sid}" with a connected participant and host'))
def _active_session_with_cohort(bdd, sid):
    state.session_id = sid
    state.session_type = "workshop"
    state.daemon_ws = object()
    bdd["participant_ws"] = AsyncMock()
    bdd["host_ws"] = AsyncMock()
    state.participants = {"pax": bdd["participant_ws"], "__host__": bdd["host_ws"]}
    _populate_session_caches()


# ── When: page / API / WS / handler actions ─────────────────────────────────


@when(parsers.parse('a browser opens the stale session page "{path}"'))
def _open_stale_page(bdd, path):
    bdd["resp"] = bdd["client"].get(path, follow_redirects=False)


@when(parsers.parse('a browser probes the unknown session status "{path}"'))
def _probe_unknown_status(bdd, path):
    bdd["resp"] = bdd["client"].get(path, follow_redirects=False)


@when(parsers.parse('a participant connects to the stale session socket "{path}"'))
def _connect_stale_socket(bdd, path):
    frame = None
    with bdd["client"].websocket_connect(path) as ws:
        frame = ws.receive_json()
    bdd["ws_frame"] = frame


@when(parsers.parse('the daemon switches the active session to "{new_id}"'))
def _switch_session(bdd, new_id):
    asyncio.run(_handle_set_session_id({"session_id": new_id}))


@when("the daemon ends the active session")
def _end_session(bdd):
    # The daemon omits session_id when no session is active.
    asyncio.run(_handle_set_session_id({}))


# ── Then: page / API assertions ─────────────────────────────────────────────


@then(parsers.parse('it is redirected to "{target}"'))
def _redirected_to(bdd, target):
    resp = bdd["resp"]
    assert resp.status_code in (302, 307), f"expected a redirect, got {resp.status_code}"
    assert resp.headers["location"] == target


@then(parsers.parse('it is never redirected onto the active session "{sid}"'))
def _never_onto_active(bdd, sid):
    assert sid not in bdd["resp"].headers.get("location", "")


@then("the gateway responds 404")
def _responds_404(bdd):
    assert bdd["resp"].status_code == 404


@then(parsers.parse('the response does not expose the active session "{sid}"'))
def _no_active_in_body(bdd, sid):
    assert sid not in bdd["resp"].text


# ── Then: WebSocket assertions ──────────────────────────────────────────────


@then(parsers.parse('the socket receives a redirect to "{target}"'))
def _socket_redirect(bdd, target):
    assert bdd["ws_frame"] == {"type": "redirect", "url": target}
    assert bdd["ws_frame"] == _INVALID_REDIRECT


@then(parsers.parse('the socket redirect does not mention the active session "{sid}"'))
def _socket_no_active(bdd, sid):
    assert sid not in json.dumps(bdd["ws_frame"])


# ── Then: session-switch cohort assertions ──────────────────────────────────


@then("the old participant is steered to the neutral error page")
def _participant_neutral(bdd):
    bdd["participant_ws"].send_text.assert_called_once_with(json.dumps(_INVALID_REDIRECT))


@then(parsers.parse('the old participant is never steered onto "{a}" nor "{b}"'))
def _participant_never_onto(bdd, a, b):
    sent = bdd["participant_ws"].send_text.call_args[0][0]
    assert a not in sent and b not in sent


@then("the old participant socket is closed")
def _participant_closed(bdd):
    bdd["participant_ws"].close.assert_called_once_with(1008)


@then("the old cohort's cached state is cleared")
def _caches_wiped(bdd):
    assert _caches_cleared()
    assert "pax" not in state.participants


@then("the active session is cleared")
def _session_cleared(bdd):
    assert state.session_id is None
