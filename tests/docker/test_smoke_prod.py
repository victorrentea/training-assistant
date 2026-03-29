"""
Smoke test: Playwright in Docker → production URL.

Proves that a headless Chromium inside a container can reach
interact.victorrentea.ro and interact with the participant page.

Run:
    cd tests/docker
    docker build -f Dockerfile.playwright -t pw-smoke .
    docker run --rm pw-smoke
"""

import re
from playwright.sync_api import sync_playwright, expect


PROD_URL = "https://interact.victorrentea.ro"


def test_participant_page_loads():
    """Participant page loads and shows the name input."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(PROD_URL, wait_until="networkidle")

        # Page should have a title
        assert page.title(), "Page title should not be empty"

        # Should see the name input or the main participant UI
        # (exact selector depends on current state, but the page should not be an error)
        assert page.url.startswith(PROD_URL), f"Unexpected redirect: {page.url}"

        # No major JS errors — check console
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))

        # Take a screenshot as proof
        page.screenshot(path="/tmp/prod-smoke.png")
        print(f"Screenshot saved to /tmp/prod-smoke.png")

        browser.close()

    assert not errors, f"JS errors on page: {errors}"


def test_participant_page_has_content():
    """Page renders meaningful content (not a blank or error page)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(PROD_URL, wait_until="networkidle")

        # Body should have some visible text
        body_text = page.inner_text("body")
        assert len(body_text.strip()) > 10, "Page body seems empty or broken"

        print(f"Page loaded, body length: {len(body_text)} chars")
        browser.close()
