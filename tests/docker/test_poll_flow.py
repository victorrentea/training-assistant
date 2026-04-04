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
        pax1.vote_for("Python")
        print("Alice voted Python")
        pax2.vote_for("Go")
        print("Bob voted Go")

        # Host sees vote count update ("N of M voted" while poll is active)
        expect(host_raw.locator("#vote-progress-label")).to_contain_text("2 of", timeout=10000)
        print("Host sees 2 votes")

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
