"""Hermetic E2E: the participant URL reflects the active tab.

- Deep-link /<session>/files lands on the Files tab.
- Clicking the Activity nav rewrites the address bar to the bare /<session> URL
  (Activity is the default landing tab, so its link stays clean — no suffix).
- The standalone read-only notes page lives at /<session>/notes-print.
"""

import sys

import pytest

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

from pages.participant_page import ParticipantPage
from playwright.sync_api import expect, sync_playwright
from session_utils import fresh_session

pytestmark = pytest.mark.nightly

BASE = "http://localhost:8000"


def test_tab_url_deeplink_and_rewrite():
    session_id = fresh_session("TabUrl")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        # Deep-link directly to the (ungated) Files tab.
        page.goto(f"{BASE}/{session_id}/files", wait_until="networkidle")
        ParticipantPage(page).auto_join()
        expect(page.locator("#files-view")).to_be_visible(timeout=10000)
        expect(page.locator("#slides-view")).to_be_hidden()
        # Switching to the Activity (default landing) tab rewrites the address bar
        # back to the bare session URL — its shareable link carries no tab suffix.
        page.locator('[data-nav="activity"]').click()
        expect(page.locator("#activity-view")).to_be_visible(timeout=10000)
        page.wait_for_url(f"{BASE}/{session_id}", timeout=5000)
        assert page.url.rstrip("/").endswith(f"/{session_id}")
        browser.close()


def test_notes_print_page_served():
    session_id = fresh_session("NotesPrint")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        # The standalone notes page is its own document (static/notes.html),
        # distinct from the participant SPA. Assert the route SERVES that document:
        # HTTP 200 whose body is the notes page (its <title> + heading markup).
        # We assert on the captured HTTP response body rather than the live DOM,
        # because the page's on-load JS may client-side redirect (when a fresh
        # session has no notes yet) before any DOM assertion can run.
        resp = page.goto(f"{BASE}/{session_id}/notes-print", wait_until="commit")
        assert resp is not None and resp.status == 200, (
            f"/{session_id}/notes-print did not return 200: {resp}"
        )
        served_html = resp.text()
        assert "<title>Session Notes</title>" in served_html, (
            f"/notes-print did not serve the notes page document:\n{served_html[:500]}"
        )
        assert "Session Notes & Key Points" in served_html, (
            f"/notes-print body missing the notes heading:\n{served_html[:500]}"
        )
        browser.close()
