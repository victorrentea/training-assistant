import base64
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from playwright.sync_api import sync_playwright, expect

from pages.participant_page import ParticipantPage
from session_utils import daemon_has_participant


BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:8081")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")
_AUTH = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()


def _req(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{DAEMON_BASE}{path}",
        method=method,
        headers={
            "Authorization": f"Basic {_AUTH}",
            "Content-Type": "application/json",
        },
        data=data,
    )
    if method == "POST" and body is None:
        req.add_header("Content-Length", "0")
        req.data = b""
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _wait_until(fn, timeout_ms: int, msg: str, poll_ms: int = 250):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if fn():
            return
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg)


@pytest.mark.nightly
def test_participant_name_survives_close_reopen():
    # Ensure clean slate.
    try:
        _req("POST", "/api/session/end")
    except Exception:
        pass

    session_name = f"Restore Name {int(time.time())}"
    started = _req("POST", "/api/session/create", {"name": session_name, "type": "workshop"})
    session_id = started["session_id"]
    assert session_id

    _wait_until(
        lambda: _req("GET", "/api/session/active").get("session_id") == session_id,
        timeout_ms=10000,
        msg="Session did not become active after start",
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.auto_join()
        pax.rename("Persisted Tester")
        expect(pax_page.locator("#display-name")).to_have_text("Persisted Tester", timeout=5000)

        _wait_until(
            lambda: daemon_has_participant(session_id, "Persisted Tester"),
            timeout_ms=10000,
            msg="Daemon host state did not include renamed participant",
        )

        _req("POST", "/api/session/end")
        _wait_until(
            lambda: _req("GET", "/api/session/active").get("session_id") is None,
            timeout_ms=10000,
            msg="Session did not become inactive after end",
        )

        resumed = _req("POST", "/api/session/resume", {"folder": session_name})
        resumed_id = resumed["session_id"]
        assert resumed_id

        _wait_until(
            lambda: _req("GET", "/api/session/active").get("session_id") == resumed_id,
            timeout_ms=12000,
            msg="Session did not become active after resume",
        )

        pax_page.goto(f"{BASE}/{resumed_id}", wait_until="networkidle")
        expect(pax_page.locator("#display-name")).to_have_text("Persisted Tester", timeout=10000)

        _wait_until(
            lambda: daemon_has_participant(resumed_id, "Persisted Tester"),
            timeout_ms=10000,
            msg="Restored session did not expose persisted participant name",
        )

        browser.close()
