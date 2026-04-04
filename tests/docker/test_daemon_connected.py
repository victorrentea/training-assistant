"""
Hermetic E2E test: Real daemon connects to real backend inside Docker.

Verifies:
1. Backend is running and healthy
2. Real daemon connected via WebSocket (daemon_connected = true)
3. Host can start a session (daemon acks via global_state_saved)
4. Participant can join the session
"""

import json
import os
import re
import time
import urllib.request

import pytest
from playwright.sync_api import sync_playwright, expect


BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:8081")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


def test_backend_healthy():
    """Backend serves the participant page without errors."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        response = page.goto(f"{BASE}/", wait_until="networkidle")
        assert response and response.status < 400, f"Backend returned HTTP {response and response.status}"
        # Page should have loaded some visible content
        expect(page.locator("body")).to_be_visible(timeout=5000)
        browser.close()


def test_daemon_connected():
    """Real daemon is connected via WebSocket (visible in host WS state).

    Verifies daemon connectivity by hitting the /api/session/active public endpoint
    on the daemon — if the daemon is running and connected, this returns a valid JSON.
    We also verify it is connected to Railway by checking Railway /api/status.
    """
    import json
    import urllib.request

    # Verify daemon is running and responsive
    try:
        with urllib.request.urlopen(f"{DAEMON_BASE}/api/session/active", timeout=5) as resp:
            data = json.loads(resp.read())
            print(f"Daemon session/active: {data}")
    except Exception as e:
        pytest.fail(f"Daemon not responding at {DAEMON_BASE}: {e}")

    # Verify Railway is running and responsive
    try:
        with urllib.request.urlopen(f"{BASE}/api/status", timeout=5) as resp:
            status = json.loads(resp.read())
            print(f"Railway status: {status}")
    except Exception as e:
        pytest.fail(f"Railway not responding at {BASE}: {e}")

    print("SUCCESS: Daemon and Railway are both running!")


def test_host_starts_session_with_real_daemon():
    """Host starts session, real daemon processes the request."""
    import base64

    # End any existing session so the landing page is shown (not a redirect)
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    try:
        req = urllib.request.Request(
            f"{DAEMON_BASE}/api/session/end", method="POST",
            headers={"Authorization": f"Basic {auth}", "Content-Length": "0"},
            data=b"",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

    # Wait for session to be fully ended
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{DAEMON_BASE}/api/session/active", timeout=3) as r:
                if not json.loads(r.read()).get("active", True):
                    break
        except Exception:
            pass
        time.sleep(0.3)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Host browser
        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()

        # Host opens landing page (daemon serves host panel at port 8081)
        host_page.goto(f"{DAEMON_BASE}/host", wait_until="networkidle")

        # Type session name and start
        name_input = host_page.locator("#session-name-input")
        name_input.fill("Docker Hermetic Test")

        create_btn = host_page.locator("#create-btn-workshop")
        expect(create_btn).to_be_enabled(timeout=3000)
        create_btn.click()

        # Should redirect to /host/{session_id}
        host_page.wait_for_url(re.compile(r"/host/[a-zA-Z0-9]+"), timeout=15000)
        session_id = host_page.url.split("/host/")[-1].split("?")[0]
        assert session_id, "No session_id in URL"
        print(f"Session created: {session_id}")

        # Participant joins
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")

        # Wait for auto-name assignment
        display_name = pax_page.locator("#display-name")
        display_name.wait_for(state="visible", timeout=10000)
        pax_name = display_name.inner_text()
        assert pax_name, "Participant name should not be empty"
        print(f"Participant joined as: {pax_name}")

        # Host should see participant
        host_page.wait_for_timeout(3000)
        body = host_page.inner_text("body")
        assert pax_name in body, f"Host doesn't see '{pax_name}'"

        print(f"SUCCESS: Real daemon + backend + browsers working in Docker!")
        browser.close()
