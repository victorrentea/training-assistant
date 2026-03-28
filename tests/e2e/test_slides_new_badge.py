"""
E2E tests for the slides NEW badge and native-mode update banner.

Rules under test:
1. NEW badge appears only if the participant previously visited the slide AND
   the slide was updated after that visit.
2. NEW badge does NOT appear for a slide the participant has never opened.
3. In PDF.js mode (default), when the currently-viewed slide is updated the
   viewer auto-reloads and the NEW badge is cleared without user interaction.
4. In native mode, the auto-reload is suppressed to preserve scroll position.
   Instead, a banner "New version available — click to reload" appears; clicking
   it loads the new version and clears the badge.
"""

import io
import time

import pytest
import requests
from playwright.sync_api import Page, expect

from conftest import HOST_USER, HOST_PASS, pax_browser_ctx

# ── Minimal valid PDF ────────────────────────────────────────────────────────
_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]>>endobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF\n"
)

_SLUG = "e2e-new-badge-slide"
_ITEM_SEL = f'[data-slide-id*="{_SLUG}"]'
_NEW_BADGE_SEL = f'{_ITEM_SEL} .slides-list-new'
_BANNER_SEL = "#slides-native-update-banner"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _upload(server_url: str) -> None:
    """Upload (or re-upload) the test slide to trigger an updated_at change."""
    resp = requests.post(
        f"{server_url}/api/slides/upload",
        auth=(HOST_USER, HOST_PASS),
        files={"file": (f"{_SLUG}.pdf", io.BytesIO(_MINIMAL_PDF), "application/pdf")},
        data={"slug": _SLUG, "name": "E2E New Badge Slide"},
    )
    assert resp.status_code == 200, resp.text


def _delete(server_url: str) -> None:
    requests.post(
        f"{server_url}/api/materials/delete",
        auth=(HOST_USER, HOST_PASS),
        json={"relative_path": f"slides/{_SLUG}.pdf"},
    )


def _open_slide(page: Page) -> None:
    """Click the slide open-button so it is marked visited and the overlay opens."""
    page.locator(f"{_ITEM_SEL} button.slides-list-open").click()
    # Overlay opens and PDF.js (or native frame) starts loading.
    expect(page.locator("#slides-overlay.open")).to_be_visible(timeout=8_000)


def _close_overlay(page: Page) -> None:
    page.keyboard.press("Escape")
    expect(page.locator("#slides-overlay.open")).not_to_be_visible(timeout=4_000)


# ── Fixtures ─────────────────────────────────────────────────────────────────

class TestSlidesNewBadge:
    @pytest.fixture(autouse=True)
    def setup_and_teardown(self, server_url):
        _delete(server_url)
        _upload(server_url)   # v1 always present before each test
        yield
        _delete(server_url)

    # ── 1. Badge does NOT appear before first visit ───────────────────────────
    def test_no_badge_before_first_visit(self, server_url, playwright):
        """Slide is updated but the participant never opened it — no NEW badge."""
        browser, ctx = pax_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        try:
            page.goto("/")
            expect(page.locator("#main-screen")).to_be_visible(timeout=10_000)
            # Wait for the slide to appear in the list.
            expect(page.locator(f"{_ITEM_SEL}:not(.unavailable)")).to_be_visible(timeout=8_000)

            # Small delay so mtime changes between v1 and v2 uploads.
            time.sleep(0.05)
            _upload(server_url)  # v2

            # Give the WebSocket broadcast + catalog refresh time to complete.
            time.sleep(1.5)

            # Badge must NOT exist — participant never opened the slide.
            expect(page.locator(_NEW_BADGE_SEL)).not_to_be_visible()
        finally:
            ctx.close()
            browser.close()

    # ── 2. Badge appears after visiting and then updating ────────────────────
    def test_badge_appears_after_update(self, server_url, playwright):
        """Participant visits the slide, then the host updates it → NEW badge appears."""
        browser, ctx = pax_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        try:
            page.goto("/")
            expect(page.locator("#main-screen")).to_be_visible(timeout=10_000)
            expect(page.locator(f"{_ITEM_SEL}:not(.unavailable)")).to_be_visible(timeout=8_000)

            # Visit the slide.
            _open_slide(page)
            _close_overlay(page)

            # Ensure mtime will be different on re-upload.
            time.sleep(0.05)
            _upload(server_url)  # v2

            # NEW badge should appear (visited + updated).
            expect(page.locator(_NEW_BADGE_SEL)).to_be_visible(timeout=8_000)
        finally:
            ctx.close()
            browser.close()

    # ── 3. Badge disappears after re-clicking (PDF.js manual reload) ─────────
    def test_badge_clears_after_click(self, server_url, playwright):
        """Clicking the slide after it is updated clears the NEW badge."""
        browser, ctx = pax_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        try:
            page.goto("/")
            expect(page.locator("#main-screen")).to_be_visible(timeout=10_000)
            expect(page.locator(f"{_ITEM_SEL}:not(.unavailable)")).to_be_visible(timeout=8_000)

            _open_slide(page)
            _close_overlay(page)

            time.sleep(0.05)
            _upload(server_url)  # v2

            # Wait for badge.
            expect(page.locator(_NEW_BADGE_SEL)).to_be_visible(timeout=8_000)

            # Re-open the slide → badge must disappear.
            _open_slide(page)
            expect(page.locator(_NEW_BADGE_SEL)).not_to_be_visible(timeout=5_000)
        finally:
            ctx.close()
            browser.close()

    # ── 4. PDF.js auto-reload clears badge without user interaction ──────────
    def test_pdfjs_autoreload_clears_badge(self, server_url, playwright):
        """With overlay open in PDF.js mode, the slide auto-reloads on update
        and the NEW badge is cleared automatically."""
        browser, ctx = pax_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        try:
            page.goto("/")
            expect(page.locator("#main-screen")).to_be_visible(timeout=10_000)
            expect(page.locator(f"{_ITEM_SEL}:not(.unavailable)")).to_be_visible(timeout=8_000)

            # Open slide and keep the overlay open.
            _open_slide(page)
            expect(page.locator("#slides-overlay.open")).to_be_visible(timeout=8_000)

            time.sleep(0.05)
            _upload(server_url)  # v2

            # After auto-reload completes the badge should be gone.
            # Allow enough time for: WS broadcast + catalog refresh + PDF.js reload.
            expect(page.locator(_NEW_BADGE_SEL)).not_to_be_visible(timeout=10_000)
        finally:
            ctx.close()
            browser.close()

    # ── 5. Native mode: banner appears, banner click clears badge ────────────
    def test_native_mode_banner_appears_and_clears(self, server_url, playwright):
        """In native viewer mode a 'New version available' banner appears when
        the current slide is updated; clicking it loads the new version and
        clears both the banner and the NEW badge."""
        browser, ctx = pax_browser_ctx(server_url, playwright)
        # Pre-set native view mode so the page opens in native mode.
        ctx.add_init_script(
            "localStorage.setItem('workshop_slides_view_mode', 'native')"
        )
        page = ctx.new_page()
        try:
            page.goto("/")
            expect(page.locator("#main-screen")).to_be_visible(timeout=10_000)
            expect(page.locator(f"{_ITEM_SEL}:not(.unavailable)")).to_be_visible(timeout=8_000)

            # Open the slide in native mode.
            _open_slide(page)

            time.sleep(0.05)
            _upload(server_url)  # v2

            # Banner should appear (no auto-reload in native mode).
            expect(page.locator(_BANNER_SEL)).to_be_visible(timeout=8_000)

            # Click the banner to reload.
            page.locator(_BANNER_SEL).click()

            # Banner must disappear after reload.
            expect(page.locator(_BANNER_SEL)).not_to_be_visible(timeout=6_000)

            # Close overlay and verify badge is gone too.
            _close_overlay(page)
            expect(page.locator(_NEW_BADGE_SEL)).not_to_be_visible()
        finally:
            ctx.close()
            browser.close()
