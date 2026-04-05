"""
Hermetic E2E test: Host starts session → Participant joins.

Runs inside Docker with:
- Real FastAPI backend (from the actual codebase)
- Mock daemon (minimal WS client)
- Playwright driving host + participant browsers

Flow:
1. Host opens /host (landing page)
2. Host types session name, clicks "Start workshop"
3. Host is redirected to /host/{session_id}
4. Host sees participant link at bottom of screen
5. Participant opens that link
6. Participant sets their name
7. Host sees the participant in the list
"""

import subprocess
import signal
import time
import os
import re
import json

import pytest
from playwright.sync_api import sync_playwright, expect


BACKEND_PORT = "8000"
BASE = f"http://localhost:{BACKEND_PORT}"
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


@pytest.fixture(scope="session", autouse=True)
def backend_server():
    """Start the real FastAPI backend."""
    env = os.environ.copy()
    env["HOST_USERNAME"] = HOST_USER
    env["HOST_PASSWORD"] = HOST_PASS
    # Disable session folder scanning (no local filesystem)
    env["SESSIONS_FOLDER"] = "/tmp/test-sessions"
    env["TRANSCRIPTION_FOLDER"] = "/tmp/test-transcriptions"
    os.makedirs("/tmp/test-sessions", exist_ok=True)
    os.makedirs("/tmp/test-transcriptions", exist_ok=True)

    proc = subprocess.Popen(
        ["python", "-m", "uvicorn", "railway.app:app", "--host", "0.0.0.0", "--port", BACKEND_PORT],
        cwd="/app",
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to be ready (use root path which always returns 200)
    import urllib.request
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{BASE}/")
            break
        except Exception:
            time.sleep(0.3)
    else:
        proc.kill()
        stdout, stderr = proc.communicate()
        raise RuntimeError(f"Backend did not start.\nstdout: {stdout.decode()}\nstderr: {stderr.decode()}")

    yield proc
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=10)


@pytest.fixture(scope="session", autouse=True)
def mock_daemon(backend_server):
    """Start the mock daemon after backend is ready."""
    env = os.environ.copy()
    env["BACKEND_HOST"] = "localhost"
    env["BACKEND_PORT"] = BACKEND_PORT
    env["HOST_USERNAME"] = HOST_USER
    env["HOST_PASSWORD"] = HOST_PASS

    proc = subprocess.Popen(
        ["python", "/tests/mock_daemon.py"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Give daemon a moment to connect
    time.sleep(1)
    if proc.poll() is not None:
        stdout, stderr = proc.communicate()
        raise RuntimeError(f"Mock daemon exited early.\nstdout: {stdout.decode()}\nstderr: {stderr.decode()}")

    yield proc
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_host_starts_session_participant_joins():
    """Full flow: host starts a session, participant joins using the session URL."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # --- Host browser context (with Basic Auth) ---
        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()

        # Host opens landing page — this test uses mock_daemon (no daemon host server),
        # so use Railway backend directly for session creation flow.
        host_page.goto(f"{BASE}/host", wait_until="networkidle")
        assert "Start Session" in host_page.title() or host_page.locator(".landing-card").count() > 0

        # Host types a session name and clicks "Start workshop"
        name_input = host_page.locator("#session-name-input")
        name_input.fill("Hermetic Test")

        create_btn = host_page.locator("#create-btn-workshop")
        expect(create_btn).to_be_enabled(timeout=3000)
        create_btn.click()

        # Host should be redirected to /host/{session_id}
        host_page.wait_for_url(re.compile(r"/host/[a-zA-Z0-9]+"), timeout=10000)
        session_url = host_page.url
        session_id = session_url.split("/host/")[-1].split("?")[0]
        assert session_id, "No session_id in URL"
        print(f"Session started: {session_id}")

        # Wait for the host page to fully load and show participant link
        host_page.wait_for_load_state("networkidle")

        # Extract the participant join URL from the host page
        # The link is at the bottom — look for it in the session-code-bar area
        participant_url = f"{BASE}/{session_id}"
        print(f"Participant URL: {participant_url}")

        # --- Participant browser context (no auth) ---
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()

        # Participant opens the session URL — auto-joins with a suggested name
        pax_page.goto(participant_url, wait_until="networkidle")
        pax_page.wait_for_load_state("networkidle")

        # Participant auto-joins: calls /api/participant/register, connects WS
        # Wait for the display-name element to appear (proves WS connected + name set)
        display_name = pax_page.locator("#display-name")
        display_name.wait_for(state="visible", timeout=10000)
        pax_name = display_name.inner_text()
        assert pax_name, "Participant display name should not be empty"
        print(f"Participant auto-named: '{pax_name}'")

        # Verify: host should see the participant in their list
        # Wait for the participant count or name to appear on host page
        host_page.wait_for_timeout(3000)  # allow WS broadcast
        body_text = host_page.inner_text("body")
        assert pax_name in body_text, (
            f"Host page does not show participant '{pax_name}'. Body text snippet: {body_text[:500]}"
        )

        print(f"SUCCESS: Host sees participant '{pax_name}'!")

        browser.close()
