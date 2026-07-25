"""Tests for the railway-gateway hardening fixes (branch fix/harden-gateway).

Harness: the REAL ``railway.app:app`` driven either in-process via
``fastapi.testclient.TestClient`` (HTTP + a simulated daemon WebSocket that
answers set_session_id / proxy_request) or by calling the WS message handlers
directly with ``AsyncMock`` sockets. No docker image and no live daemon needed.

Five fixes, each with a test:

1. Session-switch cross-cohort steer — on a session change/end every
   no-longer-valid participant socket must receive the neutral
   ``{"type":"redirect","url":"/?error=invalid"}`` frame + close 1008, never
   the NEW session id (residual cross-cohort hijack) nor the OLD id.
2. Daemon-reconnect ~5s self-stall — the daemon receive loop must start BEFORE
   the blocking ``broadcast_slides_updated()`` /api/slides proxy, so a freshly
   announced session becomes active well under PROXY_TIMEOUT (5s).
3. Inbound IP rate-limiting — session-probe / status / page routes trip under a
   flood while leaving a generous per-IP budget for real participants.
4. Backend per-session reset + stale session_id invalidation — caches are
   dropped on a session switch, and a lingering session_id after the daemon
   disconnects no longer reports the session as active.
5. Content-Security-Policy on railway-served HTML pages, allow-listing exactly
   the CDNs the pages actually load so nothing breaks.
"""
import base64
import json
import os
import re
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from railway.app import app
from railway.features.pages.router import _CSP
from railway.features.ws import router as ws_router
from railway.features.ws.router import (
    _INVALID_REDIRECT,
    _clear_session_caches,
    _evict_all_clients_after_grace,
    _handle_set_session_id,
)
from railway.shared.rate_limit import TokenBucketLimiter, probe_limiter
from railway.shared.state import state

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _reset_gateway_state():
    """Every test starts from a clean singleton state and full rate-limit budget."""
    state.reset()
    probe_limiter.reset()
    yield
    ws_router._cancel_pending_kick()
    state.reset()
    probe_limiter.reset()


def _daemon_auth_headers() -> dict:
    """Basic-auth header matching ``_is_host_authorized_for_ws`` (env or defaults)."""
    user = os.environ.get("HOST_USERNAME") or "host"
    pw = os.environ.get("HOST_PASSWORD") or "host"
    creds = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


def _populate_session_caches() -> None:
    """Fill every per-session cache so a test can prove they get cleared."""
    state.slides = [{"slug": "intro"}]
    state.slides_updated = {"intro": {"status": "cached"}}
    state.uploaded_files = {"u1": [{"id": 0, "filename": "a.pdf"}]}
    state.upload_next_id = 7
    state.participant_history = {"u1"}
    state.participant_ips = {"u1": "1.2.3.4"}
    state.participant_names = {"u1": "Alice"}
    state.participant_avatars = {"u1": "avatar"}


def _assert_caches_cleared() -> None:
    assert state.slides == []
    assert state.slides_updated == {}
    assert state.uploaded_files == {}
    assert state.upload_next_id == 0
    assert state.participant_history == set()
    assert state.participant_ips == {}
    assert state.participant_names == {}
    assert state.participant_avatars == {}


# ---------------------------------------------------------------------------
# Fix 1 — session-switch / session-end cross-cohort steer
# ---------------------------------------------------------------------------

class TestCrossCohortSteer:
    @pytest.mark.anyio
    async def test_session_switch_steers_old_cohort_to_neutral_landing(self):
        """A switch to a NEW id must NOT send the old cohort onto the new session.

        This is the residual-hijack case: previously the participant frame was
        ``/{new_id}`` (or the old id), letting one cohort land inside another.
        Contract: always the neutral ``/?error=invalid`` + close 1008.
        """
        state.session_id = "old111"
        state.session_type = "workshop"
        participant_ws = AsyncMock()
        host_ws = AsyncMock()
        state.participants = {"pax": participant_ws, "__host__": host_ws}
        _populate_session_caches()

        await _handle_set_session_id({"session_id": "new222"})

        assert state.session_id == "new222"
        # Old-cohort participant → neutral landing, never "/new222" nor "/old111".
        participant_ws.send_text.assert_called_once_with(json.dumps(_INVALID_REDIRECT))
        participant_ws.close.assert_called_once_with(1008)
        sent = participant_ws.send_text.call_args[0][0]
        assert "new222" not in sent and "old111" not in sent
        # Host is authorized for the new session → steered to its host page.
        host_ws.send_text.assert_called_once_with(
            json.dumps({"type": "redirect", "url": "/host/new222"})
        )
        host_ws.close.assert_called_once_with(1000)
        # Old cohort dropped; caches wiped (Fix 4 runs on the same path).
        assert "pax" not in state.participants
        assert "__host__" not in state.participants
        _assert_caches_cleared()

    @pytest.mark.anyio
    async def test_session_end_steers_old_cohort_to_neutral_landing(self):
        """Ending the session (no new id) also uses the neutral redirect + 1008."""
        state.session_id = "old111"
        participant_ws = AsyncMock()
        state.participants = {"pax": participant_ws}

        await _handle_set_session_id({})  # daemon omits session_id when none active

        assert state.session_id is None
        participant_ws.send_text.assert_called_once_with(json.dumps(_INVALID_REDIRECT))
        participant_ws.close.assert_called_once_with(1008)

    @pytest.mark.anyio
    async def test_grace_eviction_steers_old_cohort_and_invalidates_session(self, monkeypatch):
        """After the daemon stays gone past the grace window, participants get the
        neutral redirect and the now-stale session id is invalidated (Fix 1 + 4)."""
        monkeypatch.setattr(ws_router, "_DAEMON_DISCONNECT_GRACE_SECONDS", 0.01)
        monkeypatch.setattr(ws_router, "broadcast_slides_updated", AsyncMock())
        state.session_id = "old111"
        state.daemon_ws = None  # daemon is gone
        participant_ws = AsyncMock()
        host_ws = AsyncMock()
        state.participants = {"pax": participant_ws, "__host__": host_ws}
        _populate_session_caches()

        await _evict_all_clients_after_grace()

        participant_ws.send_text.assert_called_once_with(json.dumps(_INVALID_REDIRECT))
        participant_ws.close.assert_called_once_with(1008)
        # Session invalidated so status/require_valid_session stop honouring it.
        assert state.session_id is None
        _assert_caches_cleared()
        assert state.participants == {}


# ---------------------------------------------------------------------------
# Fix 2 — daemon-reconnect self-stall (session active well under PROXY_TIMEOUT)
# ---------------------------------------------------------------------------

class TestDaemonReconnectNoStall:
    def test_set_session_id_processed_well_under_proxy_timeout(self, monkeypatch):
        """A simulated daemon connects and announces a session; the backend must
        process set_session_id near-instantly.

        In the buggy ordering the connect handler ``await``s the /api/slides
        proxy BEFORE starting the receive loop, so the announcement is not read
        until the proxy times out at PROXY_TIMEOUT (~5s). We deliberately do NOT
        answer the background proxy_request — proving the receive loop runs
        regardless — and assert the session lands in well under that window.
        """
        # Keep the post-disconnect eviction from lingering after the test.
        monkeypatch.setattr(ws_router, "_DAEMON_DISCONNECT_GRACE_SECONDS", 0.05)
        client = TestClient(app)
        with client.websocket_connect("/ws/daemon", headers=_daemon_auth_headers()) as ws:
            ws.send_json({"type": "set_session_id", "session_id": "sess01"})
            start = time.monotonic()
            while time.monotonic() - start < 4.0:
                if state.session_id == "sess01":
                    break
                time.sleep(0.02)
            elapsed = time.monotonic() - start

        assert state.session_id == "sess01", (
            "set_session_id never processed — receive loop stalled behind the slides proxy"
        )
        assert elapsed < 3.0, (
            f"set_session_id took {elapsed:.2f}s (>=3s): the daemon receive loop is "
            "blocked behind the /api/slides proxy (PROXY_TIMEOUT self-stall regressed)"
        )


# ---------------------------------------------------------------------------
# Fix 3 — inbound IP rate-limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_token_bucket_allows_capacity_then_blocks_then_refills(self):
        """Deterministic bucket behaviour with an injected clock."""
        lim = TokenBucketLimiter(capacity=5, refill_per_sec=10)
        t = 0.0
        assert all(lim.allow("ip-a", now=t) for _ in range(5))  # full budget
        assert not lim.allow("ip-a", now=t)                     # then throttled
        # 0.35s later → 3.5 tokens refilled (10/s): exactly 3 more allowed.
        granted = [lim.allow("ip-a", now=t + 0.35) for _ in range(4)]
        assert granted == [True, True, True, False]
        # Independent keys keep independent budgets.
        assert lim.allow("ip-b", now=t)

    def test_status_endpoint_trips_429_under_flood(self, monkeypatch):
        """A flood of status probes from one client IP eventually gets 429s while
        the first (legitimate) probes succeed, and a 429 carries Retry-After."""
        monkeypatch.delenv("GATEWAY_RATE_LIMIT_DISABLED", raising=False)
        client = TestClient(app)

        first = client.get("/api/status")
        assert first.status_code == 200  # generous budget: real users are fine

        throttled = None
        for _ in range(300):
            r = client.get("/api/status")
            if r.status_code == 429:
                throttled = r
                break
        assert throttled is not None, "status flood was never rate-limited"
        assert throttled.headers.get("Retry-After") == "1"

        # Budget recovers once the limiter is reset (simulates refill over time).
        probe_limiter.reset()
        assert client.get("/api/status").status_code == 200

    def test_invalid_session_probe_is_rate_limited(self, monkeypatch):
        """The 200-vs-404 enumeration oracle: even invalid-session probes (which
        404) must be throttled — rate_limit_probe runs before require_valid_session."""
        monkeypatch.delenv("GATEWAY_RATE_LIMIT_DISABLED", raising=False)
        client = TestClient(app)
        codes = {client.get("/zzzzzz/api/status").status_code for _ in range(300)}
        assert 404 in codes, "expected 404 for an invalid session id"
        assert 429 in codes, "invalid-session enumeration was not throttled"


# ---------------------------------------------------------------------------
# Fix 4 — backend per-session reset + stale session_id gating
# ---------------------------------------------------------------------------

class TestSessionResetAndStaleGating:
    def test_clear_session_caches_empties_all_per_session_state(self):
        _populate_session_caches()
        _clear_session_caches()
        _assert_caches_cleared()

    def test_status_session_active_requires_daemon_present(self, monkeypatch):
        """A lingering session_id after the daemon drops must NOT read as active."""
        monkeypatch.setenv("GATEWAY_RATE_LIMIT_DISABLED", "1")  # isolate from Fix 3
        client = TestClient(app)

        state.session_id = "abc123"
        state.daemon_ws = None
        assert client.get("/api/status").json()["session_active"] is False

        state.daemon_ws = object()  # daemon reconnected (any non-None socket)
        assert client.get("/api/status").json()["session_active"] is True


# ---------------------------------------------------------------------------
# Fix 5 — Content-Security-Policy on railway-served HTML
# ---------------------------------------------------------------------------

# host -> the CSP directive that must allow it, per tag kind.
_SERVED_PAGES = [
    "static/landing.html",
    "static/host.html",
    "static/participant.html",
    "static/talk.html",
    "static/notes.html",
    "static/host-landing.html",
    "static/new/code.html",
]


def _csp_directives() -> dict[str, set[str]]:
    """Parse _CSP into {directive: {tokens}}."""
    out: dict[str, set[str]] = {}
    for chunk in _CSP.split(";"):
        parts = chunk.split()
        if parts:
            out[parts[0]] = set(parts[1:])
    return out


class TestContentSecurityPolicy:
    def test_pages_carry_the_csp_header(self, monkeypatch):
        monkeypatch.setenv("GATEWAY_RATE_LIMIT_DISABLED", "1")
        client = TestClient(app)
        state.session_id = "sess01"  # participant routes require a valid session

        for path in ("/", "/sess01/", "/sess01/notes-print"):
            resp = client.get(path)
            assert resp.status_code == 200, path
            assert resp.headers.get("content-security-policy") == _CSP, path

    def test_csp_contains_hardening_directives(self):
        d = _csp_directives()
        assert d["default-src"] == {"'self'"}
        assert d["object-src"] == {"'none'"}
        assert d["base-uri"] == {"'self'"}
        assert d["frame-ancestors"] == {"'self'"}
        assert d["form-action"] == {"'self'"}
        # connect-src is restricted (no wildcard) to blunt exfiltration.
        assert "*" not in " ".join(d["connect-src"])
        assert "'self'" in d["connect-src"]

    def test_csp_allowlists_every_external_asset_the_pages_load(self):
        """Audit: each external <script src>/<link stylesheet href> host used by a
        served page must be allow-listed in the matching CSP directive, so the
        policy tightens security without breaking the pages."""
        d = _csp_directives()
        script_src = d["script-src"]
        style_src = d["style-src"]

        violations: list[str] = []
        for rel in _SERVED_PAGES:
            f = _PROJECT_ROOT / rel
            if not f.is_file():
                continue
            html = f.read_text(encoding="utf-8", errors="replace")

            for tag in re.findall(r"<script\b[^>]*>", html, re.I):
                for host in re.findall(r'src=["\']https://([a-zA-Z0-9.-]+)', tag):
                    if f"https://{host}" not in script_src:
                        violations.append(f"{rel}: script host {host} not in script-src")

            for tag in re.findall(r"<link\b[^>]*>", html, re.I):
                if "stylesheet" not in tag.lower():
                    continue
                for host in re.findall(r'href=["\']https://([a-zA-Z0-9.-]+)', tag):
                    if f"https://{host}" not in style_src:
                        violations.append(f"{rel}: style host {host} not in style-src")

        assert not violations, "CSP would break page assets:\n" + "\n".join(violations)
