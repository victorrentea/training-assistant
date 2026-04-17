"""
Hermetic E2E test: participant onboarding overlay.

- First visit (cleared storage) → overlay visible after loading screen hides.
- Click any emoji button → overlay dismissed, localStorage flag set.
- Reload → overlay does NOT reappear.
"""

import os
import re
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

from playwright.sync_api import sync_playwright, expect

from session_utils import fresh_session


BASE = "http://localhost:8000"


def test_onboarding_first_visit_shows_and_dismisses():
    session_id = fresh_session("OnboardingTest")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(f"{BASE}/{session_id}", wait_until="networkidle")

        # Wait for loading screen to hide and overlay to become visible.
        overlay = page.locator("#onboarding-overlay")
        expect(overlay).to_have_class(re.compile(r"\bvisible\b"), timeout=10000)

        # Tooltip is also visible.
        tooltip = page.locator("#onboarding-tooltip")
        expect(tooltip).to_have_class(re.compile(r"\bvisible\b"))

        # Click the first emoji button in the main bar.
        first_emoji = page.locator("#emoji-main-bar button").first
        first_emoji.click()

        # Overlay loses the `visible` class within ~500 ms.
        time.sleep(0.6)
        overlay_class = overlay.get_attribute("class") or ""
        assert "visible" not in overlay_class, (
            f"overlay still has 'visible' class after dismissal: {overlay_class}"
        )

        # localStorage flag is set.
        flag = page.evaluate(
            "() => localStorage.getItem('workshop_onboarding_seen')"
        )
        assert flag == "1", f"expected flag '1', got {flag!r}"

        # Reload — overlay must NOT reappear.
        page.reload(wait_until="networkidle")
        time.sleep(0.5)
        overlay_class_after_reload = overlay.get_attribute("class") or ""
        assert "visible" not in overlay_class_after_reload, (
            f"overlay reappeared after reload: {overlay_class_after_reload}"
        )

        browser.close()
