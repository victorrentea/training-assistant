"""Hermetic E2E: a fresh participant lands on Slides with "follow" already ticked.

The trainer's ask: "when a participant connects they should land on the slides tab
with follow ticked — the moment I open the slides they land there, I do nothing."

What is pinned here:
- a first-visit participant lands on #slides-view with #slides-follow-checkbox checked;
- an explicit deep link (/<session>/files) still wins over that default;
- an explicit tab choice survives a reload — the default does not fight the user.
"""

import sys

import pytest
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

from pages.participant_page import ParticipantPage  # noqa: E402
from session_utils import fresh_session  # noqa: E402

pytestmark = pytest.mark.nightly

BASE = "http://localhost:8000"


def test_fresh_participant_lands_on_slides_with_follow_ticked():
    session_id = fresh_session("DefaultLanding")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # A brand-new context = empty localStorage = a participant who never chose a tab.
        page = browser.new_context().new_page()
        page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        ParticipantPage(page).auto_join()

        expect(page.locator("#slides-view")).to_be_visible(timeout=10000)
        expect(page.locator("#activity-view")).to_be_hidden()
        expect(page.locator("#slides-follow-checkbox")).to_be_checked(timeout=5000)
        browser.close()


def test_deep_link_still_beats_the_slides_default():
    session_id = fresh_session("DefaultLandingDeepLink")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context().new_page()
        page.goto(f"{BASE}/{session_id}/files", wait_until="networkidle")
        ParticipantPage(page).auto_join()

        expect(page.locator("#files-view")).to_be_visible(timeout=10000)
        expect(page.locator("#slides-view")).to_be_hidden()
        browser.close()


def test_explicit_tab_choice_survives_a_reload():
    session_id = fresh_session("DefaultLandingSticky")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()  # same context on reload => same localStorage
        page = ctx.new_page()
        page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        ParticipantPage(page).auto_join()
        expect(page.locator("#slides-view")).to_be_visible(timeout=10000)

        page.locator('[data-nav="activity"]').click()
        expect(page.locator("#activity-view")).to_be_visible(timeout=5000)
        page.wait_for_url(f"{BASE}/{session_id}", timeout=5000)

        page.reload(wait_until="networkidle")
        ParticipantPage(page).dismiss_gate_anonymous(timeout=2000)
        expect(page.locator("#activity-view")).to_be_visible(timeout=10000)
        expect(page.locator("#slides-view")).to_be_hidden()
        browser.close()
