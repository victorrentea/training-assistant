"""
Hermetic regression test: Session end survives daemon WS reconnect.

Bug: POST /api/session/end sets session_request={"action":"end"} and pushes it
to the daemon via WS. If the WS drops at that moment, the message is lost.
On reconnect, the daemon's _sync_session_on_reconnect fires and re-sends
session_sync(active), which _apply_session_main() accepted blindly — reactivating
a session the host had explicitly ended.

Fix:
_apply_session_main() blocks re-activation while session_request.action=="end".

This test exercises _apply_session_main() directly via POST /api/{session_id}/session/sync
(the same code path called by the WS session_sync handler), simulating a daemon
that reconnects and pushes session_sync(active) after the host ended the session.
"""

import base64
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

import pytest

BACKEND_PORT = os.environ.get("BACKEND_PORT_SESSION_END", "8001")
BASE = f"http://localhost:{BACKEND_PORT}"
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")

# Resolve app root — works both in Docker (/app) and local dev
_HERE = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.environ.get("APP_ROOT") or (
    "/app" if os.path.isdir("/app") else os.path.normpath(os.path.join(_HERE, "..", ".."))
)


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _api(method, path, data=None):
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    body = json.dumps(data).encode() if data else (b"" if method == "POST" else None)
    req = urllib.request.Request(
        f"{BASE}{path}", method=method,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        data=body,
    )
    if method == "POST" and data is None:
        req.add_header("Content-Length", "0")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _session_active() -> bool:
    try:
        return _api("GET", "/api/session/active").get("active", False)
    except Exception:
        return False


# ── Fixtures ─────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def backend():
    """Start a real FastAPI backend on BACKEND_PORT, shut it down after the module."""
    env = os.environ.copy()
    env.update({
        "HOST_USERNAME": HOST_USER,
        "HOST_PASSWORD": HOST_PASS,
        "SESSIONS_FOLDER": "/tmp/test-sessions-session-end",
        "TRANSCRIPTION_FOLDER": "/tmp/test-transcriptions-session-end",
    })
    os.makedirs("/tmp/test-sessions-session-end", exist_ok=True)
    os.makedirs("/tmp/test-transcriptions-session-end", exist_ok=True)

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "main:app",
            "--host", "0.0.0.0", "--port", BACKEND_PORT,
        ],
        cwd=APP_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait until healthy
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{BASE}/api/session/active")
            break
        except Exception:
            time.sleep(0.3)
    else:
        proc.kill()
        out, err = proc.communicate()
        raise RuntimeError(
            f"Backend did not start.\nstdout: {out.decode()}\nstderr: {err.decode()}"
        )

    yield proc
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=10)


# ── Test ─────────────────────────────────────────────────────────────────────────

@pytest.mark.nightly
def test_session_end_survives_daemon_reconnect_reactivation(backend):
    """
    Daemon reconnect after session end must NOT reactivate the session.

    Scenario:
      1. Create session and sync it as active via HTTP (simulates daemon startup sync).
      2. Host calls POST /api/session/end → session becomes inactive.
      3. Simulate daemon reconnect: call POST /api/{id}/session/sync with active main
         (same code path as WS session_sync message from a reconnecting daemon).
      4. Assert: session stays inactive despite the re-sync.

    Without the fix, step 3 would call _apply_session_main({"status": "active"})
    unconditionally → session reactivated (BUG).
    With the fix, _apply_session_main() detects pending "end" and ignores the sync.
    """
    session_name = f"end-reconnect-{int(time.time())}"

    # ── 1. Create session and mark it as active via HTTP sync ─────────────────
    result = _api("POST", "/api/session/create", {"name": session_name, "type": "workshop"})
    session_id = result["session_id"]
    assert session_id, "Expected a session_id from /api/session/create"

    _api("POST", f"/api/{session_id}/session/sync", {
        "main": {
            "name": session_name,
            "status": "active",
            "started_at": "2026-01-01T10:00:00",
        },
        "key_points": [],
    })
    assert _session_active(), "Session should be active after sync"

    # ── 2. Host ends the session ──────────────────────────────────────────────
    _api("POST", "/api/session/end")
    assert not _session_active(), "Session should be inactive after POST /api/session/end"

    # ── 3. Simulate daemon reconnect re-syncing session as active (the bug) ───
    # This is what _sync_session_on_reconnect() does on every WS reconnect:
    # it calls POST /api/{id}/session/sync with the session still in the stack.
    _api("POST", f"/api/{session_id}/session/sync", {
        "main": {
            "name": session_name,
            "status": "active",
            "started_at": "2026-01-01T10:00:00",
        },
        "key_points": [],
    })

    # ── 4. Assert: session must STILL be inactive ─────────────────────────────
    assert not _session_active(), (
        "BUG: daemon reconnect reactivated an explicitly-ended session. "
        "_apply_session_main() must block re-activation while session_request.action == 'end'."
    )
