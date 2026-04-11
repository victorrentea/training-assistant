"""
Hermetic E2E test: PPTX update triggers Railway hash-check retry and participant auto-refresh.

Flow:
1. Participant follows host's current slide (page 3 of "Clean Code")
2. PPTX file is touched (mtime change) → daemon detects and sends download_pdf
   with check_changed=True to Railway
3. Railway downloads PDF, compares hash — initially unchanged (Google Drive
   hasn't published yet), retries every 5s
4. After ~10s the fixture PDF is swapped to a new version (7 pages)
5. Railway detects hash change → stores new PDF → sends pdf_download_complete
   with changed=True → daemon broadcasts slides_cache_status with refreshed_slugs
6. Participant auto-refreshes and sees the updated PDF (7 pages) at page 3
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

from pages.participant_page import ParticipantPage  # noqa: E402
from session_utils import fresh_session  # noqa: E402

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:8081")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")
TRANSCRIPTION_FOLDER = Path(os.environ.get("TRANSCRIPTION_FOLDER", "/tmp/test-transcriptions"))
FIXTURE_PDF_DIR = Path(os.environ.get("FIXTURE_PDF_DIR", "/tmp/fixture-pdfs"))

SLUG = "clean-code"
PRESENTATION = "Clean Code.pptx"
PPTX_PATH = Path("/tmp/test-pptx") / PRESENTATION
HOST_PAGE = 3
NEW_PAGE_COUNT = 7  # original fixture has 5 pages


# ── Helpers ──────────────────────────────────────────────────────────────────


def _activity_slides_file() -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    return TRANSCRIPTION_FOLDER / f"activity-slides-{today}.md"


def _set_slide_pointer(deck: str, slide: int):
    f = _activity_slides_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(f"{deck}:{slide}\n")


def _clear_slide_pointer():
    _activity_slides_file().unlink(missing_ok=True)


def _await_condition(fn, timeout_ms=10_000, poll_ms=300, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def _backend_slides_current_slug() -> str | None:
    import base64
    try:
        auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
        req = urllib.request.Request(
            f"{BASE}/api/status",
            headers={"Authorization": f"Basic {auth}"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            sc = data.get("slides_current")
            return sc.get("slug") if sc else None
    except Exception:
        return None


def _prime_slide_cache(session_id: str) -> None:
    """Download the slide PDF via daemon /check so Railway has a cached copy."""
    import base64
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    url = f"{DAEMON_BASE}/{session_id}/api/slides/check/{SLUG}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=35) as resp:
        assert resp.status == 200, f"/check returned {resp.status}"


def _minimal_pdf(num_pages: int, title: str = "Test Slide") -> bytes:
    """Generate a minimal valid PDF with numbered pages (no external deps)."""
    objects = []
    obj_id = 0

    def add_obj(content: str) -> int:
        nonlocal obj_id
        obj_id += 1
        objects.append((obj_id, content))
        return obj_id

    catalog_id = add_obj("")
    pages_id = add_obj("")
    font_id = add_obj("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_ids = []
    for page_num in range(1, num_pages + 1):
        text = f"Page {page_num} of {num_pages} - {title}"
        stream = f"BT /F1 24 Tf 100 400 Td ({text}) Tj ET"
        stream_id = add_obj(
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
        )
        page_id = add_obj(
            f"<< /Type /Page /Parent {pages_id} 0 R "
            f"/MediaBox [0 0 612 792] "
            f"/Contents {stream_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        )
        page_ids.append(page_id)

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[pages_id - 1] = (pages_id, f"<< /Type /Pages /Kids [{kids}] /Count {num_pages} >>")
    objects[catalog_id - 1] = (catalog_id, f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    lines = [b"%PDF-1.4\n"]
    offsets = {}
    for oid, content in objects:
        offsets[oid] = len(b"".join(lines))
        lines.append(f"{oid} 0 obj\n{content}\nendobj\n".encode())

    xref_offset = len(b"".join(lines))
    lines.append(b"xref\n")
    lines.append(f"0 {len(objects) + 1}\n".encode())
    lines.append(b"0000000000 65535 f \n")
    for oid in range(1, len(objects) + 1):
        lines.append(f"{offsets[oid]:010d} 00000 n \n".encode())

    lines.append(b"trailer\n")
    lines.append(f"<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n".encode())
    lines.append(b"startxref\n")
    lines.append(f"{xref_offset}\n".encode())
    lines.append(b"%%EOF\n")

    return b"".join(lines)


def _swap_fixture_pdf_after_delay(delay_s: float):
    """Replace the fixture PDF with a new version (more pages) after a delay.

    Runs in a background thread. Mock Drive serves from disk, so swapping
    the file makes the next download return the new content.
    """
    import threading

    def _swap():
        time.sleep(delay_s)
        new_pdf = _minimal_pdf(NEW_PAGE_COUNT, "Clean Code UPDATED")
        fixture_path = FIXTURE_PDF_DIR / f"{SLUG}.pdf"
        fixture_path.write_bytes(new_pdf)
        print(f"[test] Swapped fixture PDF to {NEW_PAGE_COUNT} pages after {delay_s}s")

    t = threading.Thread(target=_swap, daemon=True)
    t.start()
    return t


def _restore_fixture_pdf():
    """Restore the original 5-page fixture PDF."""
    original_pdf = _minimal_pdf(5, "Clean Code")
    fixture_path = FIXTURE_PDF_DIR / f"{SLUG}.pdf"
    fixture_path.write_bytes(original_pdf)


# ── Test ─────────────────────────────────────────────────────────────────────


@pytest.mark.nightly
def test_pptx_update_triggers_participant_refresh():
    """
    End-to-end: PPTX mtime change → daemon sends download_pdf with check_changed
    → Railway retries until Google Drive has new version → participant auto-refreshes.
    """
    SWAP_DELAY_S = 10  # seconds before mock Drive starts serving new PDF

    _clear_slide_pointer()
    _set_slide_pointer(PRESENTATION, HOST_PAGE)

    session_id = fresh_session("PptxUpdateRefresh")

    # Prime cache so Railway has the old 5-page PDF
    _prime_slide_cache(session_id)
    print(f"[test] Cache primed with original {SLUG} PDF")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            # Host page (needed for slides_current broadcast)
            host_ctx = browser.new_context(
                http_credentials={"username": HOST_USER, "password": HOST_PASS}
            )
            host_page = host_ctx.new_page()
            host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
            expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10_000)

            # Participant joins with follow mode ON (fresh context = default ON)
            pax_ctx = browser.new_context()
            pax_page = pax_ctx.new_page()
            pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
            pax = ParticipantPage(pax_page)
            pax.join("UpdateWatcher")

            # Wait for daemon to push slides_current
            _await_condition(
                lambda: _backend_slides_current_slug() == SLUG,
                timeout_ms=15_000,
                msg=f"Daemon did not push slides_current for '{SLUG}' within 15s",
            )
            print(f"[test] Backend slides_current slug='{SLUG}' ✓")

            # Wait for participant to have the slide loaded (follow auto-triggers)
            expect(pax_page.locator("#slides-overlay.open")).to_be_visible(timeout=20_000)
            expect(pax_page.locator("#slides-page-inline")).to_contain_text(
                f"Page {HOST_PAGE}/", timeout=15_000
            )
            print(f"[test] Participant following host at page {HOST_PAGE} ✓")

            # Track download requests to detect auto-refresh
            download_requests = []
            pax_page.on(
                "request",
                lambda req: download_requests.append(req.url)
                if f"/api/slides/download/{SLUG}" in req.url
                else None,
            )
            download_requests.clear()

            # Schedule fixture PDF swap (simulates Google Drive publishing new version)
            swap_thread = _swap_fixture_pdf_after_delay(SWAP_DELAY_S)

            # Touch the PPTX to trigger daemon mtime detection
            PPTX_PATH.touch()
            print(f"[test] Touched {PPTX_PATH} to trigger mtime change")

            # Daemon scans every ~10s, detects mtime change, sends download_pdf
            # with check_changed=True. Railway retries until hash changes (~10s).
            # After Railway gets new PDF, daemon broadcasts refreshed_slugs.
            # Participant auto-reloads.
            # Total wait: ~10s (daemon scan) + ~10s (Drive delay) + ~5s (buffer) = ~25s

            # Wait for participant to re-download the slide
            _await_condition(
                lambda: len(download_requests) > 0,
                timeout_ms=60_000,
                poll_ms=500,
                msg=f"Participant did not auto-refresh slide '{SLUG}' after PPTX update within 60s",
            )
            print("[test] Participant re-downloaded slide ✓")

            # Verify participant still on the correct page with updated page count
            expect(pax_page.locator("#slides-page-inline")).to_contain_text(
                f"Page {HOST_PAGE}/", timeout=10_000
            )

            # Verify the new PDF has the expected page count
            page_text = pax_page.locator("#slides-page-inline").inner_text()
            assert f"/{NEW_PAGE_COUNT}" in page_text, (
                f"Expected {NEW_PAGE_COUNT} total pages in updated PDF, got: {page_text}"
            )
            print(f"[test] Updated PDF has {NEW_PAGE_COUNT} pages, showing page {HOST_PAGE} ✓")

            swap_thread.join(timeout=2)
            browser.close()

    finally:
        _clear_slide_pointer()
        _restore_fixture_pdf()
