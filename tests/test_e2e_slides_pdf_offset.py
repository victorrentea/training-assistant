"""
E2E validation for participant PDF.js scroll offset persistence.
"""

from __future__ import annotations

import uuid
from io import BytesIO

from playwright.sync_api import expect
from pypdf import PdfWriter

from conftest import api, pax_browser_ctx
from pages.participant_page import ParticipantPage


def _make_multi_page_pdf(page_count: int = 3, page_height: int = 2200) -> bytes:
    """Create a valid multi-page PDF for deterministic scroll testing."""
    assert page_count >= 1
    assert page_height >= 800
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=page_height)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _upload_slide_pdf(server_url: str, slug: str, name: str) -> None:
    pdf_bytes = _make_multi_page_pdf(page_count=3, page_height=2200)
    upload = api(
        server_url,
        "post",
        "/api/slides/upload",
        data={"slug": slug, "name": name},
        files={"file": ("offset-deck.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload.status_code == 200, upload.text


def _open_slide_and_wait(page, name: str) -> None:
    page.evaluate("toggleSlidesModal()")
    page.wait_for_function(
        "() => document.getElementById('slides-overlay')?.classList.contains('open') === true",
        timeout=5000,
    )
    expect(page.locator(f".slides-list-item:has-text('{name}')")).to_be_visible(timeout=10000)
    page.locator(f".slides-list-item:has-text('{name}') .slides-list-open").click(force=True)
    page.wait_for_function(
        "() => document.querySelectorAll('#slides-pdf-container .page').length > 0",
        timeout=30000,
    )
    page.wait_for_function(
        "() => { const c = document.getElementById('slides-pdf-container'); return !!c && c.scrollHeight > c.clientHeight + 300; }",
        timeout=15000,
    )


def _read_stored_view(page, slug: str):
    return page.evaluate(
        "(key) => JSON.parse(localStorage.getItem(key) || 'null')",
        f"workshop_slide_view:{slug}",
    )


def _assert_manual_scroll_persisted(page, slug: str):
    page.locator("#slides-pdf-container").hover()
    page.mouse.wheel(0, 1400)
    page.wait_for_function(
        "(key) => { try { const raw = localStorage.getItem(key); if (!raw) return false; const v = JSON.parse(raw); return Number(v?.scrollTop || 0) > 50; } catch (_) { return false; } }",
        arg=f"workshop_slide_view:{slug}",
        timeout=10000,
    )
    stored = _read_stored_view(page, slug)
    visible_scroll = page.evaluate(
        "() => Number(document.getElementById('slides-pdf-container')?.scrollTop || 0)"
    )
    assert stored is not None
    assert stored["scrollTop"] > 50
    assert abs(stored["scrollTop"] - visible_scroll) < 220
    assert int(stored["page"]) >= 1
    return stored


def _assert_programmatic_scroll_persisted(page, slug: str, base_scroll: float):
    target_scroll = int(base_scroll) + 420
    page.evaluate(
        "(target) => { const c = document.getElementById('slides-pdf-container'); if (c) c.scrollTop = target; }",
        target_scroll,
    )
    page.wait_for_function(
        "(args) => { const c = document.getElementById('slides-pdf-container'); const raw = localStorage.getItem(args.key); if (!c || !raw) return false; const v = JSON.parse(raw); return Math.abs(Number(v.scrollTop || 0) - Number(c.scrollTop || 0)) < 180 && Math.abs(Number(c.scrollTop || 0) - Number(args.target || 0)) < 180; }",
        arg={"key": f"workshop_slide_view:{slug}", "target": target_scroll},
        timeout=10000,
    )
    stored = _read_stored_view(page, slug)
    assert stored is not None
    assert abs(float(stored["scrollTop"]) - target_scroll) < 220
    return stored


def _assert_reload_restores_scroll(page, target_scroll: float):
    page.reload()
    expect(page.locator("#main-screen")).to_be_visible(timeout=10000)
    page.evaluate(
        "() => { const overlay = document.getElementById('slides-overlay'); if (overlay && !overlay.classList.contains('open')) toggleSlidesModal(); }"
    )
    page.wait_for_function(
        "() => document.getElementById('slides-overlay')?.classList.contains('open') === true",
        timeout=10000,
    )
    page.wait_for_function(
        "() => document.querySelectorAll('#slides-pdf-container .page').length > 0",
        timeout=30000,
    )
    page.wait_for_function(
        "(target) => { const c = document.getElementById('slides-pdf-container'); return !!c && Math.abs(Number(c.scrollTop || 0) - Number(target || 0)) < 220; }",
        arg=float(target_scroll),
        timeout=12000,
    )


def test_participant_pdfjs_scroll_offset_manual_and_restore(server_url, playwright):
    slug = f"offset-{uuid.uuid4().hex[:8]}"
    name = f"Offset Deck {slug[-4:]}"
    _upload_slide_pdf(server_url, slug, name)

    browser, ctx = pax_browser_ctx(server_url, playwright)
    page = ctx.new_page()
    page.goto("/")
    pax = ParticipantPage(page)

    try:
        pax.join("PdfOffsetUser")
        _open_slide_and_wait(page, name)
        stored_after_manual = _assert_manual_scroll_persisted(page, slug)
        stored_after_programmatic = _assert_programmatic_scroll_persisted(
            page,
            slug,
            base_scroll=float(stored_after_manual["scrollTop"]),
        )
        _assert_reload_restores_scroll(
            page,
            target_scroll=float(stored_after_programmatic["scrollTop"]),
        )
    finally:
        ctx.close()
        browser.close()
