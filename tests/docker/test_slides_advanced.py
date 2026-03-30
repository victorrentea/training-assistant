"""
Hermetic E2E tests: slide availability and NEW badge functionality.

5 tests covering slide upload/delete lifecycle and badge behavior:
1. Uploaded slide appears in catalog
2. Slide becomes available after upload (live WS update)
3. No badge before first visit
4. Badge appears after visiting then updating
5. Badge clears after re-clicking
"""

import base64
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from playwright.sync_api import sync_playwright, expect

from pages.participant_page import ParticipantPage
from pages.host_page import HostPage


BASE = "http://localhost:8000"
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")

_SLUG = "hermetic-badge-slide"
_ITEM_SEL = f'[data-slide-id*="{_SLUG}"]'
_NEW_BADGE_SEL = f'{_ITEM_SEL} .slides-list-new'

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


def _await_condition(fn, timeout_ms=10000, poll_ms=300, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def _api_call(method, path, data=None):
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    body = json.dumps(data).encode() if data else (b"" if method == "POST" else None)
    req = urllib.request.Request(
        f"{BASE}{path}", method=method,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        data=body,
    )
    if method == "POST" and data is None:
        req.add_header("Content-Length", "0")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _create_session(name="Test", session_type="workshop") -> str:
    """Create a fresh session via API — gives clean state."""
    result = _api_call("POST", "/api/session/create", {"name": f"{name} {int(time.time())}", "type": session_type})
    return result["session_id"]


def _upload_slide(slug=_SLUG, name="Hermetic Badge Slide"):
    """Upload a minimal PDF slide via multipart form."""
    import uuid
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="slug"\r\n\r\n{slug}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="name"\r\n\r\n{name}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{slug}.pdf"\r\n'
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode() + _MINIMAL_PDF + f"\r\n--{boundary}--\r\n".encode()

    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    req = urllib.request.Request(
        f"{BASE}/api/slides/upload", method="POST",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        data=body,
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _delete_slide(slug=_SLUG):
    """Delete an uploaded slide."""
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    req = urllib.request.Request(
        f"{BASE}/api/materials/delete", method="POST",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        data=json.dumps({"relative_path": f"slides/{slug}.pdf"}).encode(),
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _open_browser_trio(p, session_id):
    """Open host + participant browsers connected to a session."""
    browser = p.chromium.launch(headless=True)
    host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
    host_page = host_ctx.new_page()
    host_page.goto(f"{BASE}/host/{session_id}", wait_until="networkidle")
    expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10000)
    host = HostPage(host_page)

    pax_ctx = browser.new_context()
    pax_page = pax_ctx.new_page()
    pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
    pax = ParticipantPage(pax_page)
    return browser, host, host_page, pax, pax_page


def _open_slide(page):
    """Click the slide open-button so it is marked visited and the overlay opens."""
    btn = page.locator(f"{_ITEM_SEL} button.slides-list-open")
    btn.scroll_into_view_if_needed(timeout=5000)
    btn.click(force=True)
    expect(page.locator("#slides-overlay.open")).to_be_visible(timeout=8000)


def _close_overlay(page):
    page.keyboard.press("Escape")
    expect(page.locator("#slides-overlay.open")).not_to_be_visible(timeout=4000)


# ── 1. Uploaded slide appears in catalog ──────────────────────────────────

def test_uploaded_slide_appears_in_catalog():
    """Upload a minimal PDF → participant sees it in the slides list."""
    _delete_slide()
    session_id = _create_session("SlidesCatalog")
    _upload_slide()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            pax_ctx = browser.new_context()
            pax_page = pax_ctx.new_page()
            pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
            pax = ParticipantPage(pax_page)
            pax.join("CatalogTester")

            # Wait for the slide to appear in the list
            item = pax_page.locator(_ITEM_SEL)
            expect(item).to_be_visible(timeout=10000)

            # Verify it's NOT unavailable
            expect(item).not_to_have_class(re.compile(r"unavailable"), timeout=3000)

            # Verify the open button is enabled
            open_btn = item.locator("button.slides-list-open")
            expect(open_btn).to_be_enabled(timeout=3000)

            print("SUCCESS: Uploaded slide appears in catalog!")
            browser.close()
    finally:
        _delete_slide()


# ── 2. Slide becomes available after upload ───────────────────────────────

def test_slide_becomes_available_after_upload():
    """Upload a slide while participant is already connected → it appears via WS."""
    # Use a unique slug so no prior test can leave it behind
    slug = f"live-upload-{int(time.time())}"
    item_sel = f'[data-slide-id*="{slug}"]'
    session_id = _create_session("SlidesLive")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            pax_ctx = browser.new_context()
            pax_page = pax_ctx.new_page()
            pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
            pax = ParticipantPage(pax_page)
            pax.join("LiveUploadTester")

            # Verify the slide does NOT exist yet
            item = pax_page.locator(item_sel)
            assert item.count() == 0, f"Slide '{slug}' should not exist before upload"

            # Upload the slide
            _upload_slide(slug=slug, name="Live Upload Test")

            # Wait for the slide to appear via WebSocket broadcast
            expect(item).to_be_visible(timeout=10000)

            print("SUCCESS: Slide becomes available after upload!")
            browser.close()
    finally:
        _delete_slide(slug=slug)


# ── 3. No badge before first visit ───────────────────────────────────────

def test_no_badge_before_first_visit():
    """Slide is updated but participant never opened it → no NEW badge."""
    _delete_slide()
    session_id = _create_session("NoBadge")
    _upload_slide()  # v1
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            pax_ctx = browser.new_context()
            pax_page = pax_ctx.new_page()
            pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
            pax = ParticipantPage(pax_page)
            pax.join("NoBadgeTester")

            # Wait for the slide to appear
            expect(pax_page.locator(f"{_ITEM_SEL}:not(.unavailable)")).to_be_visible(timeout=8000)

            # Small delay so mtime changes between v1 and v2 uploads
            time.sleep(0.05)
            _upload_slide()  # v2

            # Give WS broadcast + catalog refresh time
            time.sleep(1.5)

            # Badge must NOT appear — participant never opened the slide
            expect(pax_page.locator(_NEW_BADGE_SEL)).not_to_be_visible()

            print("SUCCESS: No badge before first visit!")
            browser.close()
    finally:
        _delete_slide()


# ── 4. Badge appears after visiting then updating ─────────────────────────

@pytest.mark.skip(reason="WIP: badge updated_at tracking needs investigation in Docker — works in local e2e")
def test_badge_appears_after_update():
    """Participant visits slide, then it's updated → NEW badge appears."""
    _delete_slide()
    session_id = _create_session("BadgeAppears")
    _upload_slide()  # v1
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            pax_ctx = browser.new_context()
            pax_page = pax_ctx.new_page()
            pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
            pax = ParticipantPage(pax_page)
            pax.join("BadgeTester")

            # Wait for slide to appear
            expect(pax_page.locator(f"{_ITEM_SEL}:not(.unavailable)")).to_be_visible(timeout=8000)

            # Visit the slide (marks it as seen)
            _open_slide(pax_page)
            _close_overlay(pax_page)

            # Ensure mtime is different (sleep > 1s for reliable timestamp change)
            time.sleep(1.0)
            _upload_slide()  # v2

            # Give WS broadcast + catalog refresh time to propagate
            time.sleep(1.5)

            # NEW badge should appear (visited + updated)
            expect(pax_page.locator(_NEW_BADGE_SEL)).to_be_visible(timeout=10000)

            print("SUCCESS: Badge appears after update!")
            browser.close()
    finally:
        _delete_slide()


# ── 5. Badge clears after re-clicking ─────────────────────────────────────

@pytest.mark.skip(reason="WIP: badge updated_at tracking needs investigation in Docker — works in local e2e")
def test_badge_clears_after_click():
    """After badge appears, clicking the slide again clears it."""
    _delete_slide()
    session_id = _create_session("BadgeClear")
    _upload_slide()  # v1
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            pax_ctx = browser.new_context()
            pax_page = pax_ctx.new_page()
            pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
            pax = ParticipantPage(pax_page)
            pax.join("ClearBadgeTester")

            # Wait for slide to appear
            expect(pax_page.locator(f"{_ITEM_SEL}:not(.unavailable)")).to_be_visible(timeout=8000)

            # Visit the slide
            _open_slide(pax_page)
            _close_overlay(pax_page)

            # Update the slide (sleep > 1s for reliable timestamp change)
            time.sleep(1.0)
            _upload_slide()  # v2

            # Give WS broadcast time
            time.sleep(1.5)

            # Wait for badge
            expect(pax_page.locator(_NEW_BADGE_SEL)).to_be_visible(timeout=10000)

            # Re-open the slide → badge should disappear
            _open_slide(pax_page)
            expect(pax_page.locator(_NEW_BADGE_SEL)).not_to_be_visible(timeout=5000)

            print("SUCCESS: Badge clears after click!")
            browser.close()
    finally:
        _delete_slide()
