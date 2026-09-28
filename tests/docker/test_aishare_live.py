"""Hermetic E2E: AI-share slider — host starts it, participants are routed to
the Activity view and answer with a slider, the host reveals the distribution
to everyone, then clears it."""
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest  # noqa: I001
from playwright.sync_api import expect, sync_playwright

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage
from session_utils import fresh_session

HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "host")
BASE = "http://localhost:8000"
DAEMON_BASE = "http://localhost:1234"
SHOTS = os.environ.get("SCREENSHOT_DIR")


def _shot(page, name):
    if SHOTS:
        page.wait_for_timeout(1800)  # let the bell finish rising
        page.screenshot(path=f"{SHOTS}/{name}.png", full_page=True)


@pytest.mark.nightly
def test_aishare_slider_reveal_and_clear():
    session_id = fresh_session("AiShareE2E")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS},
                                       viewport={"width": 1500, "height": 900})
        host_raw = host_ctx.new_page()
        host_raw.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_raw)

        pax = {}
        for name in ("Alice", "Bob"):
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            raw = ctx.new_page()
            raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
            pax[name] = ParticipantPage(raw)
            pax[name].join(name)
        alice, bob = pax["Alice"], pax["Bob"]
        # Park Bob elsewhere: Start must pull him back to the Activity view.
        bob._page.evaluate("showView('notes')")

        # ── Host starts → everyone lands on the slider
        host.open_aishare_tab()
        host.start_aishare()
        alice.wait_for_aishare()
        bob.wait_for_aishare()
        expect(alice._page.locator("#aishare-chart")).to_be_hidden()

        # ── Both answer; nobody sees the others yet
        alice.set_aishare(80)
        bob.set_aishare(20)
        expect(host_raw.locator("#aishare-host-status")).to_contain_text("2 answers", timeout=5000)
        expect(alice._page.locator("#aishare-status")).to_contain_text("2 colleagues", timeout=5000)
        expect(alice._page.locator("#aishare-chart")).to_be_hidden()
        _shot(alice._page, "aishare-pax-hidden")

        # ── Host reveals → both see the distribution with names
        host.reveal_aishare(True)
        expect(alice._page.locator("#aishare-chart .aishare-label")).to_have_count(2, timeout=5000)
        expect(bob._page.locator("#aishare-chart .aishare-label")).to_have_count(2, timeout=5000)
        assert sorted(alice.aishare_chart_labels()) == ["Alice · 80%", "Bob · 20%"]
        _shot(alice._page, "aishare-pax-revealed")
        _shot(host_raw, "aishare-host")

        # ── A participant moves the slider after the reveal → others see it live
        bob.set_aishare(55)
        expect(alice._page.locator("#aishare-chart")).to_contain_text("Bob · 55%", timeout=5000)

        # ── Refresh keeps Alice's answer
        alice._page.reload(wait_until="networkidle")
        alice.wait_for_aishare()
        expect(alice._page.locator("#aishare-slider")).to_have_value("80", timeout=5000)

        # ── Clear → the activity disappears for everyone
        host.clear_aishare()
        expect(alice._page.locator("#activity-aishare-section")).to_be_hidden(timeout=5000)
        expect(bob._page.locator("#activity-aishare-section")).to_be_hidden(timeout=5000)

        browser.close()
