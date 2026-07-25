"""Task-1 security follow-up: make the session_registry real so a RECENT PAST
session link resolves to a READ-ONLY "ended" view — never the live session,
never a daemon proxy, never a live participant WebSocket, and never a bare error.

Harness mirrors ``tests/test_gateway_hardening.py``: the REAL ``railway.app:app``
driven in-process via ``fastapi.testclient.TestClient``, plus direct calls into
the real ws-router handlers with ``AsyncMock`` sockets. No docker, no live daemon.

Three properties under test:

1. Registry population — ``register`` fires when a session becomes active and
   ``mark_ended`` fires when it switches / ends (via the real
   ``_handle_set_session_id`` / ``_evict_all_clients_after_grace``); TTL expiry
   drops old ids.
2. Read-only routing — a registry-valid recent-PAST id: page → the dedicated
   "session ended" view (NOT the live SPA); active id → live SPA; unknown id →
   ``/?error=invalid``.
3. Anti-hijack — a recent-past id NEVER calls ``proxy_to_daemon`` (its /api/*
   routes 404), NEVER opens a live participant WS (steered to ``/?error=invalid``),
   and its page never leaks the active session id or content.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from railway.app import app
from railway.features.ws import router as ws_router
from railway.features.ws.router import (
    _evict_all_clients_after_grace,
    _handle_set_session_id,
)
from railway.shared.rate_limit import probe_limiter
from railway.shared.session_registry import REGISTRY_TTL_DAYS, session_registry
from railway.shared.state import state

# Marker unique to the participant SPA (present in static/participant.html,
# absent from the read-only ended landing).
_SPA_MARKER = b'data-nav="activity"'
# Marker unique to the read-only ended landing (static/session-ended.html).
_ENDED_MARKER = b"This session has ended"


@pytest.fixture(autouse=True)
def _reset_state():
    """Clean singleton state, empty registry and full rate-limit budget per test."""
    state.reset()
    session_registry._entries.clear()
    probe_limiter.reset()
    _prev = os.environ.get("GATEWAY_RATE_LIMIT_DISABLED")
    os.environ["GATEWAY_RATE_LIMIT_DISABLED"] = "1"
    yield
    ws_router._cancel_pending_kick()
    state.reset()
    session_registry._entries.clear()
    probe_limiter.reset()
    if _prev is None:
        os.environ.pop("GATEWAY_RATE_LIMIT_DISABLED", None)
    else:
        os.environ["GATEWAY_RATE_LIMIT_DISABLED"] = _prev


def _register_past(session_id: str) -> None:
    """Simulate a session that ran and ended recently (registry-valid past id)."""
    session_registry.register(session_id, folder_name=session_id)
    session_registry.mark_ended(session_id)


# ---------------------------------------------------------------------------
# 1 — registry population via the real handlers
# ---------------------------------------------------------------------------

class TestRegistryPopulation:
    @pytest.mark.anyio
    async def test_activation_registers_session(self):
        """A session becoming active is recorded (register) and reads as valid."""
        assert session_registry.get("sess01") is None
        await _handle_set_session_id({"session_id": "sess01", "session_type": "workshop"})
        assert session_registry.is_valid("sess01")
        entry = session_registry.get("sess01")
        assert entry is not None and entry["ended_at"] is None  # active, not ended

    @pytest.mark.anyio
    async def test_switch_marks_old_ended_and_registers_new(self):
        """Switching sessions marks the previous one ended (now a recent-past id)
        and registers the new active one."""
        await _handle_set_session_id({"session_id": "old111"})
        await _handle_set_session_id({"session_id": "new222"})

        old = session_registry.get("old111")
        assert old is not None and old["ended_at"] is not None
        assert session_registry.is_valid("old111")  # still resolvable (recent past)
        new = session_registry.get("new222")
        assert new is not None and new["ended_at"] is None

    @pytest.mark.anyio
    async def test_end_session_marks_ended(self):
        """Ending the session (daemon omits session_id) marks it ended but keeps it
        resolvable as a recent-past id."""
        await _handle_set_session_id({"session_id": "old111"})
        await _handle_set_session_id({})
        assert state.session_id is None
        entry = session_registry.get("old111")
        assert entry is not None and entry["ended_at"] is not None
        assert session_registry.is_valid("old111")

    @pytest.mark.anyio
    async def test_grace_eviction_marks_ended(self, monkeypatch):
        """When the daemon is confirmed gone, the stale session is invalidated but
        recorded as ended so its link resolves to the read-only view."""
        monkeypatch.setattr(ws_router, "_DAEMON_DISCONNECT_GRACE_SECONDS", 0.01)

        async def _noop():
            return None

        monkeypatch.setattr(ws_router, "broadcast_slides_updated", _noop)
        await _handle_set_session_id({"session_id": "gone01"})
        state.daemon_ws = None
        await _evict_all_clients_after_grace()
        assert state.session_id is None
        entry = session_registry.get("gone01")
        assert entry is not None and entry["ended_at"] is not None
        assert session_registry.is_valid("gone01")

    @pytest.mark.anyio
    async def test_reannounce_preserves_created_at(self):
        """A daemon reconnect re-announcing the same session must not slide the TTL
        window forward (created_at is preserved)."""
        await _handle_set_session_id({"session_id": "sess01"})
        created = session_registry.get("sess01")["created_at"]
        await _handle_set_session_id({"session_id": "sess01"})
        assert session_registry.get("sess01")["created_at"] == created

    def test_ttl_expiry_drops_old_ids(self):
        """An id older than the TTL is neither valid nor kept: register()'s prune
        physically removes it."""
        session_registry.register("fresh", folder_name="fresh")
        session_registry.register("stale", folder_name="stale")
        session_registry._entries["stale"]["created_at"] = (
            datetime.now(timezone.utc) - timedelta(days=REGISTRY_TTL_DAYS + 1)
        ).isoformat()
        assert not session_registry.is_valid("stale")

        session_registry.register("trigger", folder_name="trigger")  # prunes on register
        assert session_registry.get("stale") is None
        assert session_registry.is_valid("fresh")


# ---------------------------------------------------------------------------
# 2 — read-only routing for a recent-past id
# ---------------------------------------------------------------------------

class TestReadOnlyRouting:
    def test_recent_past_page_serves_ended_view_not_live_spa(self):
        state.session_id = "livesess"
        state.daemon_ws = object()
        _register_past("pastsess")

        client = TestClient(app)
        r = client.get("/pastsess/")

        assert r.status_code == 200
        assert _ENDED_MARKER in r.content          # dedicated ended view
        assert _SPA_MARKER not in r.content        # NOT the live participant SPA
        assert b"livesess" not in r.content        # never leaks the active session
        assert b"pastsess" in r.content            # shows the requested (past) id

    def test_recent_past_tab_serves_ended_view(self):
        state.session_id = "livesess"
        _register_past("pastsess")
        client = TestClient(app)
        for tab in ("notes", "slides", "summary", "notes-print"):
            r = client.get(f"/pastsess/{tab}")
            assert r.status_code == 200, tab
            assert _ENDED_MARKER in r.content, tab
            assert _SPA_MARKER not in r.content, tab

    def test_active_id_serves_live_spa(self):
        state.session_id = "livesess"
        session_registry.register("livesess", folder_name="livesess")
        client = TestClient(app)
        r = client.get("/livesess/")
        assert r.status_code == 200
        assert _SPA_MARKER in r.content            # the live participant SPA
        assert _ENDED_MARKER not in r.content

    def test_unknown_id_redirects_to_invalid(self):
        state.session_id = "livesess"
        client = TestClient(app, follow_redirects=False)
        r = client.get("/bogus9/")
        assert r.status_code in (302, 307)
        assert r.headers["location"] == "/?error=invalid"
        # Distinct from the ended view: unknown ids never get a 200 landing.

    def test_ended_view_is_distinct_from_invalid_redirect(self):
        """A recent-past id gets a 200 read-only landing; an unknown id gets the
        302 /?error=invalid redirect — the two experiences are distinct."""
        state.session_id = "livesess"
        _register_past("pastsess")
        client = TestClient(app, follow_redirects=False)

        past = client.get("/pastsess/")
        unknown = client.get("/unknwn/")

        assert past.status_code == 200 and _ENDED_MARKER in past.content
        assert unknown.status_code in (302, 307)
        assert unknown.headers["location"] == "/?error=invalid"

    def test_case_variant_past_link_still_resolves(self):
        """Session-id matching is case-insensitive everywhere (guards, active
        check) — the registry must agree, so a case-variant past link lands on
        the ended view, not on /?error=invalid."""
        state.session_id = "livesess"
        _register_past("PastSess")
        client = TestClient(app)
        r = client.get("/pastsess/")
        assert r.status_code == 200
        assert _ENDED_MARKER in r.content
        assert _SPA_MARKER not in r.content

    @pytest.mark.parametrize("path", ["/unknwn/", "/unknwn/notes", "/unknwn/notes-print"])
    def test_page_probe_enumeration_is_rate_limited(self, path, monkeypatch):
        """UNKNOWN-id page probes (302) must burn rate-limit budget: the throttle
        runs at router level BEFORE require_valid_session. A route-level throttle
        would run AFTER the guard and never see an enumeration flood."""
        monkeypatch.delenv("GATEWAY_RATE_LIMIT_DISABLED", raising=False)
        probe_limiter.reset()
        state.session_id = "livesess"
        client = TestClient(app, follow_redirects=False)
        codes = {client.get(path).status_code for _ in range(300)}
        assert codes & {302, 307}, "expected redirects for an unknown session id"
        assert 429 in codes, f"page-probe enumeration via {path} was not throttled"


# ---------------------------------------------------------------------------
# 3 — anti-hijack: past id never reaches the live proxy / WS / content
# ---------------------------------------------------------------------------

class TestAntiHijack:
    def test_recent_past_api_routes_404_and_never_proxy(self, monkeypatch):
        """Every participant data/proxy route for a recent-past id must 404 BEFORE
        the daemon proxy — proving the old link can never read the live cohort's
        content (slides, participant proxy, uploads)."""
        state.session_id = "livesess"
        state.daemon_ws = object()  # a "connected" daemon that WOULD answer
        _register_past("pastsess")

        calls = {"n": 0}

        async def _spy_proxy(*args, **kwargs):
            calls["n"] += 1
            return JSONResponse({"leak": "live-session-content"})

        # slides.router and proxy_bridge each import proxy_to_daemon by value.
        monkeypatch.setattr("railway.features.slides.router.proxy_to_daemon", _spy_proxy)
        monkeypatch.setattr("railway.features.ws.proxy_bridge.proxy_to_daemon", _spy_proxy)

        client = TestClient(app)
        assert client.get("/pastsess/api/slides").status_code == 404
        assert client.get("/pastsess/api/slides/check/intro").status_code == 404
        assert client.get("/pastsess/api/slides/download/intro").status_code == 404
        assert client.post("/pastsess/api/upload").status_code == 404
        assert client.get("/pastsess/api/participant/register").status_code == 404
        assert client.post("/pastsess/api/participant/poll", json={}).status_code == 404

        assert calls["n"] == 0, "a recent-past id must NEVER reach proxy_to_daemon"

    def test_active_id_does_reach_proxy(self, monkeypatch):
        """Guard-rail: the active session's participant routes still proxy — the
        active-only split must not over-block live participants."""
        state.session_id = "livesess"
        state.daemon_ws = object()
        session_registry.register("livesess", folder_name="livesess")

        calls = {"n": 0}

        async def _spy_proxy(*args, **kwargs):
            calls["n"] += 1
            return JSONResponse({"ok": True})

        monkeypatch.setattr("railway.features.slides.router.proxy_to_daemon", _spy_proxy)
        client = TestClient(app)
        assert client.get("/livesess/api/slides").status_code == 200
        assert calls["n"] == 1

    def test_recent_past_websocket_steered_to_neutral_landing(self):
        """A participant socket for a recent-past id is steered to /?error=invalid
        and closed — never onto the live session (residual-hijack guard)."""
        state.session_id = "livesess"
        _register_past("pastsess")
        client = TestClient(app)
        with client.websocket_connect("/ws/pastsess/pax-uuid") as ws:
            frame = ws.receive_json()
        assert frame == {"type": "redirect", "url": "/?error=invalid"}
        assert "livesess" not in json.dumps(frame)

    def test_recent_past_session_status_not_active(self):
        """The session-scoped status endpoint reports a recent-past id as
        session_active=False (200, valid) — never confused with the live cohort."""
        state.session_id = "livesess"
        state.daemon_ws = object()
        _register_past("pastsess")
        client = TestClient(app)
        r = client.get("/pastsess/api/status")
        assert r.status_code == 200
        assert r.json()["session_active"] is False
