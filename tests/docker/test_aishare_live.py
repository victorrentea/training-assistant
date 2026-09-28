"""Hermetic E2E: AI-share slider — host starts it, participants are routed to
the Activity view and answer with a slider, the host reveals the distribution
to everyone, then clears it."""
import os
import sys
import json
import urllib.request
import uuid

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
        expect(alice._page.locator("#aishare-plot svg")).to_have_count(0)

        # ── Both answer; nobody sees the others yet
        alice.set_aishare(80)
        bob.set_aishare(20)
        expect(host_raw.locator("#aishare-host-status")).to_contain_text("2 answers", timeout=5000)
        expect(alice._page.locator("#aishare-status")).to_have_text("2 answers", timeout=5000)
        expect(alice._page.locator("#aishare-plot svg")).to_have_count(0)
        _shot(alice._page, "aishare-pax-hidden")

        # ── Host reveals → both see the distribution with names
        host.reveal_aishare(True)
        expect(alice._page.locator("#aishare-plot .aishare-dot")).to_have_count(2, timeout=5000)
        expect(bob._page.locator("#aishare-plot .aishare-dot")).to_have_count(2, timeout=5000)
        expect(alice._page.locator("#aishare-names .aishare-label")).to_have_count(0)
        expect(alice._page.locator("#aishare-value")).to_be_hidden()  # no number, the thumb says it
        # Names only on hover: the shared tooltip, instantly.
        alice._page.wait_for_timeout(1500)  # let the dots land on the curve
        alice._page.locator('#aishare-plot .aishare-dot[data-tip="Bob"][data-value="20"]').hover()
        expect(alice._page.locator("#app-tooltip.visible")).to_have_text("Bob", timeout=1000)
        _shot(alice._page, "aishare-pax-hover")
        _shot(alice._page, "aishare-pax-revealed")
        _shot(host_raw, "aishare-host")

        # ── A participant moves the slider after the reveal → others see it live
        bob.set_aishare(55)
        expect(alice._page.locator('#aishare-plot .aishare-dot[data-tip="Bob"][data-value="55"]')).to_have_count(1, timeout=5000)

        # ── Refresh keeps Alice's answer
        alice._page.reload(wait_until="networkidle")
        alice.wait_for_aishare()
        expect(alice._page.locator("#aishare-slider")).to_have_value("80", timeout=5000)

        # ── Clear → the activity disappears for everyone
        host.clear_aishare()
        expect(alice._page.locator("#activity-aishare-section")).to_be_hidden(timeout=5000)
        expect(bob._page.locator("#activity-aishare-section")).to_be_hidden(timeout=5000)

        browser.close()


CROWD = [("Ana", 10), ("Bogdan Popescu", 35), ("Cristi", 40), ("Diana", 45), ("Elena Ionescu", 50),
         ("Florin", 55), ("George", 60), ("Horia", 60), ("Ioana", 62), ("Jean-Luc Picard", 65),
         ("Kamil", 70), ("Laura", 70), ("Mihai", 70), ("Nicoleta", 75), ("Ovidiu", 80),
         ("Paula", 80), ("Radu", 85), ("Sorin", 90), ("Tudor", 95), ("Zoe", 30),
         ("Andrei", 20), ("Bianca", 65), ("Cosmin", 55), ("Dan", 100)]


def _post(url, body, pid):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Participant-ID": pid})
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status < 300


@pytest.mark.nightly
def test_aishare_fits_a_crowd_of_25():
    """24 answers seeded over REST + one real browser: every name must be drawn."""
    session_id = fresh_session("AiShareCrowd")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS},
                                       viewport={"width": 1500, "height": 900})
        host_raw = host_ctx.new_page()
        host_raw.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_raw)

        raw = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        victor = ParticipantPage(raw)
        victor.join("Victor Rentea")

        host.open_aishare_tab()
        host.start_aishare()
        victor.wait_for_aishare()
        victor.set_aishare(40)
        for name, value in CROWD:
            pid = str(uuid.uuid4())
            _post(f"{BASE}/{session_id}/api/participant/register", {"name": name}, pid)
            _post(f"{BASE}/{session_id}/api/participant/aishare/value", {"value": value}, pid)
        expect(host_raw.locator("#aishare-host-status")).to_contain_text("25 answers", timeout=5000)

        host.reveal_aishare(True)
        expect(raw.locator("#aishare-plot .aishare-dot")).to_have_count(25, timeout=5000)
        raw.wait_for_timeout(1500)
        raw.locator('#aishare-plot .aishare-dot[data-tip="Victor Rentea"][data-value="40"]').hover()
        expect(raw.locator("#app-tooltip.visible")).to_have_text("Victor Rentea", timeout=1000)
        _shot(raw, "aishare-crowd-pax")
        _shot(host_raw, "aishare-crowd-host")
        if SHOTS:
            dark = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark").new_page()
            dark.goto(f"{BASE}/{session_id}", wait_until="networkidle")
            ParticipantPage(dark).join("Dark Viewer")
            ParticipantPage(dark).wait_for_aishare()
            _shot(dark, "aishare-crowd-pax-dark")
        browser.close()
