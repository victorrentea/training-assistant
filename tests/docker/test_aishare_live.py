"""Hermetic E2E: AI-share survey — host starts it, participants are routed to
the Activity view and answer the questions one after another, the host reveals
every answer (anonymously) to everyone, then clears it."""
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


CHOICES = ["harness_work", "personal_sub", "agents_md", "knowledge_base", "mcp", "skill", "plugins", "custom_agent", "code_review", "nontech_pr"]


@pytest.mark.nightly
def test_aishare_survey_one_question_after_another_reveal_and_clear():
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
        cards = alice._page.locator("#aishare-questions .aishare-q")
        # Park Bob elsewhere: Start must pull him back to the Activity view.
        bob._page.evaluate("showView('notes')")

        # ── Host starts → everyone lands on the first question only
        host.open_aishare_tab()
        host.start_aishare()
        alice.wait_for_aishare()
        bob.wait_for_aishare()
        expect(cards).to_have_count(1)
        expect(alice._page.locator("#aishare-done")).to_be_hidden()

        # ── Each answer brings in the next question
        for i, q in enumerate(CHOICES):
            alice.choose_aishare(q, {"custom_agent": 1, "harness_work": 4}.get(q, 0))
            expect(cards).to_have_count(i + 2, timeout=5000)
        # "Other" harness: say which one
        other_box = alice.aishare_card("harness_work").locator(".aishare-other input")
        expect(other_box).to_be_visible()
        other_box.fill("Cursor")
        other_box.press("Enter")
        # Multi: ❤️ on Claude Code / Codex ticks it too, next to Other
        alice.aishare_card("harness_work").locator('.aishare-opt[data-i="0"] .aishare-heart').click()
        expect(alice.aishare_card("harness_work").locator(".aishare-opt.selected")).to_have_count(2)
        # Dragging the slider (no release yet) must not unlock the last question
        alice._page.locator("#aishare-slider-ai_generated").evaluate(
            "el => { el.value = 70; el.dispatchEvent(new Event('input', {bubbles: true})); }")
        alice._page.wait_for_timeout(1200)  # the debounced answer goes out and comes back over WS
        expect(cards).to_have_count(len(CHOICES) + 1)
        alice.set_aishare(80)
        expect(cards).to_have_count(len(CHOICES) + 2, timeout=5000)
        expect(alice._page.locator("#aishare-done")).to_be_hidden()
        alice.set_aishare(30, "review")
        expect(alice._page.locator("#aishare-done")).to_contain_text("Thank you", timeout=5000)

        for q in CHOICES:
            bob.choose_aishare(q, 2 if q == "agents_md" else (3 if q == "harness_work" else 0))
        bob.set_aishare(20)
        expect(bob.aishare_card("review")).to_be_visible(timeout=5000)

        # ── Nobody sees the others yet; the host sees everything, anonymously
        expect(host_raw.locator("#aishare-host-status")).to_contain_text("2 participants", timeout=5000)
        expect(alice.aishare_card("ai_generated").locator(".aishare-status")).to_have_text("2 answers", timeout=5000)
        expect(alice._page.locator("#aishare-questions .aishare-plot svg")).to_have_count(0)
        expect(host_raw.locator('#aishare-host-results [data-q="ai_generated"] .aishare-dot')).to_have_count(2)
        expect(host_raw.locator('#aishare-host-results [data-q="agents_md"] .aishare-bar-count')).to_have_text(["1", "1"])  # No + I don't know share a bar
        expect(host_raw.locator('#aishare-host-results [data-q="harness_work"] .aishare-other-chip')).to_have_text(["Cursor"])
        expect(host_raw.locator('#aishare-host-results [data-q="harness_work"] .aishare-bar-hearts')).to_have_text(["❤️ ×1", "", "", "", ""])
        _shot(alice._page, "aishare-pax-hidden")

        # ── Host reveals → every question, with results, for everyone
        host.reveal_aishare(True)
        expect(alice.aishare_card("ai_generated").locator(".aishare-dot")).to_have_count(2, timeout=5000)
        expect(bob._page.locator("#aishare-questions .aishare-q")).to_have_count(len(CHOICES) + 2, timeout=5000)
        expect(bob.aishare_card("agents_md").locator(".count")).to_have_text(["1", "1"])
        # Anonymous: hovering a dot tells the %, never a name.
        alice._page.wait_for_timeout(1500)  # let the dots land on the curve
        _shot(alice._page, "aishare-pax-revealed")
        expect(alice.aishare_card("ai_generated").locator(".aishare-dot[data-value=\"20\"]")).to_have_attribute("data-tip", "20%")
        expect(alice._page.locator("#activity-aishare-section")).not_to_contain_text("Bob")
        _shot(host_raw, "aishare-host")

        # ── A participant moves a slider after the reveal → others see it live
        bob.set_aishare(55)
        expect(alice.aishare_card("ai_generated").locator('.aishare-dot[data-value="55"]')).to_have_count(1, timeout=5000)

        # ── Refresh keeps Alice's answers
        alice._page.reload(wait_until="networkidle")
        alice.wait_for_aishare()
        expect(alice._page.locator("#aishare-slider-ai_generated")).to_have_value("80", timeout=5000)
        expect(alice.aishare_card("custom_agent").locator(".aishare-opt.selected")).to_have_attribute("data-i", "1")

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
    """24 answers seeded over REST + one real browser: every answer is drawn."""
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
        for name, value in CROWD:
            pid = str(uuid.uuid4())
            _post(f"{BASE}/{session_id}/api/participant/register", {"name": name}, pid)
            _post(f"{BASE}/{session_id}/api/participant/aishare/value", {"question": "ai_generated", "value": value}, pid)
        expect(host_raw.locator("#aishare-host-status")).to_contain_text("24 participants", timeout=5000)

        host.reveal_aishare(True)  # opens every question, the last slider included
        victor.set_aishare(40)
        expect(victor.aishare_card("ai_generated").locator(".aishare-dot")).to_have_count(25, timeout=5000)
        _shot(raw, "aishare-crowd-pax")
        _shot(host_raw, "aishare-crowd-host")
        if SHOTS:
            dark = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark").new_page()
            dark.goto(f"{BASE}/{session_id}", wait_until="networkidle")
            ParticipantPage(dark).join("Dark Viewer")
            ParticipantPage(dark).wait_for_aishare()
            _shot(dark, "aishare-crowd-pax-dark")
        browser.close()
