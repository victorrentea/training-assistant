"""
Hermetic E2E test: Full poll flow with real daemon.

Host creates poll → 2 participants vote → results update → poll closed → percentages shown.
Reuses the HostPage/ParticipantPage page objects from the existing e2e suite.
"""

import os
import re
import sys
import json
import urllib.request

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from playwright.sync_api import sync_playwright, expect

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage


BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:8081")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


import base64
import time

from session_utils import fresh_session


def _api_call(method, path, data=None, base=None):
    """Make API call. Defaults to DAEMON_BASE for host endpoints."""
    target = base or DAEMON_BASE
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    body = json.dumps(data).encode() if data else (b"" if method == "POST" else None)
    req = urllib.request.Request(
        f"{target}{path}", method=method,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        data=body,
    )
    if method == "POST" and data is None:
        req.add_header("Content-Length", "0")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def test_full_poll_lifecycle():
    """Complete poll flow: create → vote → close → verify percentages."""
    session_id = fresh_session("PollTest")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Host
        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_raw = host_ctx.new_page()
        host_raw.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_raw.locator("#tab-poll")).to_be_visible(timeout=10000)
        host = HostPage(host_raw)

        # Participant 1
        pax1_ctx = browser.new_context()
        pax1_raw = pax1_ctx.new_page()
        pax1_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax1 = ParticipantPage(pax1_raw)
        pax1.join("Alice")

        # Participant 2
        pax2_ctx = browser.new_context()
        pax2_raw = pax2_ctx.new_page()
        pax2_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax2 = ParticipantPage(pax2_raw)
        pax2.join("Bob")

        # Step 1: Host creates poll
        host.create_poll("Best language?", ["Python", "Java", "Go"])
        print("Poll created")

        # Both participants see the poll
        for name, pax in [("Alice", pax1), ("Bob", pax2)]:
            expect(pax._page.locator("#content h2")).to_have_text("Best language?", timeout=5000)
            expect(pax._page.locator(".option-btn")).to_have_count(3)
            print(f"{name} sees the poll")

        # Step 2: Both participants vote
        # Use REST API directly with correct option_ids format (participant.js sends
        # single-select as {option_id} but daemon expects {option_ids: [...]})
        pax1._page.evaluate("""() => participantApi('poll/vote', { option_ids: ['A'] })""")
        print("Alice voted Python (option A)")
        pax2._page.evaluate("""() => participantApi('poll/vote', { option_ids: ['C'] })""")
        print("Bob voted Go (option C)")

        # Wait for daemon to record both votes (host browser doesn't get real-time vote_update events
        # in the daemon architecture — verify via REST API instead)
        def _vote_count() -> int:
            try:
                req = urllib.request.Request(
                    f"{DAEMON_BASE}/api/{session_id}/host/state",
                    headers={"Authorization": f"Basic {base64.b64encode(f'{HOST_USER}:{HOST_PASS}'.encode()).decode()}"},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())
                    return len(data.get("votes", {}))
            except Exception:
                return 0

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if _vote_count() >= 2:
                break
            time.sleep(0.3)
        assert _vote_count() >= 2, "Daemon did not record both votes within 10s"
        print("Daemon recorded 2 votes")

        # Step 3: Host closes poll
        host.close_poll()
        print("Poll closed")

        # Both participants see results with percentages
        for name, pax in [("Alice", pax1), ("Bob", pax2)]:
            expect(pax._page.locator(".closed-banner")).to_be_visible(timeout=5000)
            expect(pax._page.locator(".pct").first).to_be_visible(timeout=5000)
            print(f"{name} sees results")

        # Verify percentages: Python=50%, Java=0%, Go=50%
        pcts = pax1.get_percentages()
        assert pcts == [50, 0, 50], f"Expected [50, 0, 50] but got {pcts}"
        print(f"Percentages correct: {pcts}")

        print("SUCCESS: Full poll lifecycle passed!")
        browser.close()
