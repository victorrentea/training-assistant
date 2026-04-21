"""
Hermetic E2E test: Participant poll countdown.

Verifies:
1. Countdown appears on participant poll card when host starts timer
2. Countdown disappears when poll ends
"""

import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest  # noqa: I001
from playwright.sync_api import expect, sync_playwright

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage
from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


@pytest.mark.nightly
def test_poll_countdown_visible_and_clears():
    """Participant sees countdown when host starts timer; it clears when poll ends."""
    session_id = fresh_session("PollCountdown")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_raw = host_ctx.new_page()
        host_raw.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_raw)

        pax_ctx = browser.new_context()
        pax_raw = pax_ctx.new_page()
        pax_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_raw)
        pax.join("Bob")

        host.create_poll("Quick question?", ["Yes", "No"])
        expect(pax_raw.locator("#activity-poll-section")).to_be_visible(timeout=5000)

        # Countdown not shown before timer starts
        assert pax.get_countdown_text() == ""

        host.start_timer(30)

        # Countdown appears and shows seconds
        expect(pax_raw.locator("#pax-countdown")).not_to_have_text("", timeout=2000)
        countdown_text = pax.get_countdown_text()
        assert "s" in countdown_text, f"Expected 's' in countdown text, got: {countdown_text!r}"

        host.close_poll()

        # Countdown clears after poll ends
        expect(pax_raw.locator("#pax-countdown")).to_have_text("", timeout=3000)

        browser.close()
