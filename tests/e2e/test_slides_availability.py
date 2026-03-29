"""
E2E tests for unavailable-slide UI:
- Catalog slides with no PDF on the server show as crossed-out and disabled.
- Once the PDF is uploaded, the slide becomes clickable in real time via WebSocket.
"""

import io
import requests
import pytest
from playwright.sync_api import expect

from conftest import HOST_USER, HOST_PASS, pax_browser_ctx, pax_url

# A minimal valid PDF accepted by PDF.js.
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

_SLUG = "e2e-unavailable-slide"
_ITEM_SEL = f'[data-slide-id*="{_SLUG}"]'


def _upload_slide(server_url: str) -> None:
    resp = requests.post(
        f"{server_url}/api/slides/upload",
        auth=(HOST_USER, HOST_PASS),
        files={"file": (f"{_SLUG}.pdf", io.BytesIO(_MINIMAL_PDF), "application/pdf")},
        data={"slug": _SLUG, "name": "E2E Unavailable Slide"},
    )
    assert resp.status_code == 200, resp.text


def _delete_uploaded_slide(server_url: str) -> None:
    requests.post(
        f"{server_url}/api/materials/delete",
        auth=(HOST_USER, HOST_PASS),
        json={"relative_path": f"slides/{_SLUG}.pdf"},
    )


class TestSlidesAvailability:
    @pytest.fixture(autouse=True)
    def ensure_slide_deleted(self, server_url):
        _delete_uploaded_slide(server_url)
        yield
        _delete_uploaded_slide(server_url)

    def test_unavailable_slide_is_crossed_out_and_disabled(self, server_url, playwright):
        browser, ctx = pax_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        try:
            page.goto(pax_url())
            expect(page.locator("#main-screen")).to_be_visible(timeout=10_000)

            unavailable = page.locator(f"{_ITEM_SEL}.unavailable")
            expect(unavailable).to_be_visible(timeout=5_000)
            expect(unavailable.locator("button.slides-list-open")).to_be_disabled()
            expect(unavailable.locator(".slides-list-download")).to_have_count(0)
        finally:
            ctx.close()
            browser.close()

    def test_slide_becomes_available_after_upload(self, server_url, playwright):
        browser, ctx = pax_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        try:
            page.goto(pax_url())
            expect(page.locator("#main-screen")).to_be_visible(timeout=10_000)

            expect(page.locator(f"{_ITEM_SEL}.unavailable")).to_be_visible(timeout=5_000)

            _upload_slide(server_url)

            # WebSocket broadcasts slides_updated → participant refreshes catalog
            available = page.locator(f"{_ITEM_SEL}:not(.unavailable)")
            expect(available).to_be_visible(timeout=8_000)
            expect(available.locator("button.slides-list-open")).to_be_enabled()
            expect(available.locator(".slides-list-download")).to_have_count(1)
        finally:
            ctx.close()
            browser.close()
