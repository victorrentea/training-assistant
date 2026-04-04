"""Shared session management utilities for hermetic Docker tests.

Every test that needs a fresh session must call `fresh_session()` instead of
directly calling the create endpoint.  The function:

1. Ends the current session (if any) so daemon's session_stack becomes empty.
2. Waits until daemon confirms no session is active.
3. Creates a new session (stack is empty → daemon syncs the new session_id to Railway).
4. Waits until Railway's /api/status returns the matching session_id.

Without this, tests 2+ run against the first test's session because the daemon
only syncs a new session to Railway when session_stack is empty.
"""

import base64
import json
import os
import time
import urllib.request
import urllib.error

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:8081")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")

_AUTH = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()


def _req(method: str, url: str, data: bytes | None = None) -> dict:
    headers = {
        "Authorization": f"Basic {_AUTH}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    if method == "POST" and data is None:
        req.add_header("Content-Length", "0")
        req.data = b""
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _get_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return {}


def _wait_until(fn, timeout_ms=8000, poll_ms=300, msg="condition not met"):
    """Poll fn() until it returns truthy or timeout."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if fn():
            return
        time.sleep(poll_ms / 1000)
    raise AssertionError(f"Timed out after {timeout_ms}ms: {msg}")


def fresh_session(name: str = "Test", session_type: str = "workshop") -> str:
    """Create a clean session, ensuring Railway knows the new session_id.

    Steps:
      1. End any active session on the daemon.
      2. Wait until daemon confirms stack is empty.
      3. Create the new session.
      4. Wait until Railway /api/status returns the matching session_id.

    Returns the new session_id string.
    """
    # Step 1: end current session (idempotent — ok even if no session active)
    try:
        _req("POST", f"{DAEMON_BASE}/api/session/end")
    except Exception:
        pass  # no active session is fine

    # Step 2: wait for daemon stack to drain
    # The /api/session/active endpoint returns {"session_id": "abc123"} when active,
    # or {"session_id": null} when empty. We check for null session_id.
    # We also check that the key exists to avoid treating daemon-not-responding as empty.
    def _session_is_empty() -> bool:
        data = _get_json(f"{DAEMON_BASE}/api/session/active")
        if "session_id" not in data:
            return False  # daemon not responding or bad response — keep waiting
        return data["session_id"] is None

    _wait_until(
        _session_is_empty,
        timeout_ms=8000,
        msg="Daemon session stack did not become empty after end",
    )

    # Step 3: create new session
    session_name = f"{name} {int(time.time())}"
    result = _req(
        "POST",
        f"{DAEMON_BASE}/api/session/create",
        json.dumps({"name": session_name, "type": session_type}).encode(),
    )
    session_id: str = result["session_id"]

    # Step 4: wait for Railway to learn the new session_id
    _wait_until(
        lambda: _get_json(f"{BASE}/api/status").get("session_id") == session_id,
        timeout_ms=10000,
        msg=f"Railway did not activate session_id={session_id!r}",
    )

    return session_id


def daemon_has_participant(session_id: str, name: str) -> bool:
    """Return True if the daemon's host state lists a participant with this name.

    Use this instead of checking host_page.inner_text('body') — Railway never
    receives participant names from daemon, so the host browser won't show them
    until it refreshes state. The daemon REST API always has the current names.
    """
    try:
        auth_header = f"Basic {_AUTH}"
        req = urllib.request.Request(
            f"{DAEMON_BASE}/api/{session_id}/host/state",
            headers={"Authorization": auth_header},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            participants = data.get("participants", [])
            return any(p.get("name") == name for p in participants)
    except Exception:
        return False
