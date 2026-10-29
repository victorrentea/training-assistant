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
import urllib.error
import urllib.request

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
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
        lambda: _get_json(f"{BASE}/{session_id}/api/status").get("session_id") == session_id,
        timeout_ms=10000,
        msg=f"Railway did not activate session_id={session_id!r}",
    )

    # Step 4b: wait for daemon main loop to process the CREATE request.
    # The router returns immediately after announce_session_id(), but the main loop
    # (which calls _participant_state.reset() and set_active_session()) runs up to 1s later.
    # Without this, participant registration may race against the reset.
    _wait_until(
        lambda: _get_json(f"{DAEMON_BASE}/api/session/active").get("session_id") == session_id,
        timeout_ms=5000,
        msg=f"Daemon did not process session creation for session_id={session_id!r}",
    )

    # Step 5: reset scores on daemon so previous test's score accumulation doesn't bleed in
    try:
        _req("DELETE", f"{DAEMON_BASE}/api/{session_id}/host/scores")
    except Exception:
        pass  # non-critical; test may still fail on score assertions but won't crash

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


class MockAddonBridge:
    """Stand-in for victor-macos-addons' WS server, which tells the daemon what the
    trainer is presenting.

    The daemon's addon-bridge client dials ws://127.0.0.1:8765 and re-dials every
    5s; each `slide_presenting_now` it receives becomes the session's current slide
    (`current_slide_updated` to every participant). That is the only way the
    current slide reaches the daemon — the old activity-slides-<date>.md pointer
    file is no longer read.

    `present()` pushes to the connected daemon and is replayed to a daemon that
    connects later. Start it after `fresh_session()`: a new session forgets the
    current slide.
    """

    def __init__(self, port: int | None = None):
        import threading

        self.port = port or int(os.environ.get("WS_SERVER_PORT", "8765"))
        self.connected = threading.Event()
        self._clients: set = set()
        self._last: str | None = None
        self._loop = None
        self._stop_evt = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        import asyncio

        try:
            asyncio.run(self._serve())
        except BaseException as exc:  # noqa: BLE001 — surfaced by __enter__
            self._error = exc
            self._ready.set()

    async def _serve(self) -> None:
        import asyncio

        import websockets

        self._loop = asyncio.get_running_loop()
        self._stop_evt = asyncio.Event()

        async def handle(ws):
            self._clients.add(ws)
            self.connected.set()
            try:
                if self._last:
                    await ws.send(self._last)
                async for _ in ws:  # drain what the daemon sends (emoji, session events)
                    pass
            except Exception:
                pass
            finally:
                self._clients.discard(ws)

        # The previous test's server may still hold the port for a moment.
        for _ in range(60):
            try:
                async with websockets.serve(handle, "127.0.0.1", self.port):
                    self._ready.set()
                    await self._stop_evt.wait()
                    return
            except OSError:
                await asyncio.sleep(0.5)
        raise OSError(f"MockAddonBridge could not bind port {self.port}")

    def present(self, deck: str, slide: int) -> None:
        import asyncio

        self._last = json.dumps(
            {"type": "slide_presenting_now", "deck": deck, "slide": slide, "presenting": True}
        )
        msg = self._last

        async def _broadcast():
            for ws in list(self._clients):
                try:
                    await ws.send(msg)
                except Exception:
                    pass

        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(_broadcast(), self._loop).result(timeout=5)

    def __enter__(self) -> "MockAddonBridge":
        self._thread.start()
        if not self._ready.wait(timeout=35) or self._error is not None:
            raise RuntimeError(f"MockAddonBridge did not start: {self._error!r}")
        return self

    def __exit__(self, *exc) -> None:
        if self._loop is not None and self._stop_evt is not None:
            self._loop.call_soon_threadsafe(self._stop_evt.set)
        self._thread.join(timeout=10)


def participant_host_slide(page) -> dict | None:
    """The host's current slide as this participant's page knows it (`_hostSlidesCurrent`).

    The current slide is daemon-resident: Railway's /api/status does not carry it.
    """
    try:
        return page.evaluate("() => window._hostSlidesCurrent || null")
    except Exception:
        return None
