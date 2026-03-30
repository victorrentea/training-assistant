"""
Hermetic E2E test: Follow mode survives slow PDF downloads from Google Drive.

Regression test for the bug where a slow Drive download (>5s) caused
follow mode to be automatically disabled mid-load.

Root cause: updateviewarea fired by PDF.js during setDocument/pagesloaded
after the initial 5s suppression window expired, triggering
_autoDisableSlidesFollowFromParticipantNav() and turning follow mode off.

Fix: suppression is renewed for 5s right before slidesPdfViewer.setDocument(),
covering the entire setDocument + scale + pagesloaded window regardless of
download time.

Test coverage:
  - 20s Drive delay → architecture deck, host on slide 2

  Only 20s is tested: 1s/5s downloads complete within the original 5s
  suppression window and would pass even without the fix, wasting ~36s.

Each case asserts:
  1. Follow mode (aria-pressed on #slides-follow-btn) is still ENABLED after load
  2. Participant is on the expected page (#slides-page-inline shows "Page X/…")
  3. The correct slide deck is active in the list (.slides-list-item.active)

Each test uses a distinct slug so there is no backend PDF cache overlap.
"""

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from playwright.sync_api import sync_playwright, expect

from pages.participant_page import ParticipantPage


BASE = "http://localhost:8000"
MOCK_DRIVE_BASE = f"http://localhost:{os.environ.get('MOCK_DRIVE_PORT', '9090')}"
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")
STUB_PPT_FILE = "/tmp/stub-powerpoint.json"

# Extra buffer on top of the Drive delay when waiting for assertions.
_ASSERT_BUFFER_S = 20


def _await_condition(fn, timeout_ms=10_000, poll_ms=300, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def _set_powerpoint_state(presentation: str, slide: int, presenting: bool = False):
    """Write stub PowerPoint state for the daemon to pick up."""
    with open(STUB_PPT_FILE, "w") as f:
        json.dump({
            "presentation": presentation,
            "slide": slide,
            "presenting": presenting,
            "frontmost": True,
        }, f)


def _clear_powerpoint_state():
    Path(STUB_PPT_FILE).unlink(missing_ok=True)


def _create_session(name: str) -> str:
    import base64
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    req = urllib.request.Request(
        f"{BASE}/api/session/create",
        method="POST",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
        data=json.dumps({"name": f"{name} {int(time.time())}", "type": "workshop"}).encode(),
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["session_id"]


def _mock_drive_set_delay(slug: str, delay_s: float):
    body = json.dumps({"slug": slug, "delay_s": delay_s}).encode()
    req = urllib.request.Request(
        f"{MOCK_DRIVE_BASE}/mock-drive/set-delay",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=body,
    )
    urllib.request.urlopen(req, timeout=5)


def _mock_drive_reset_delays():
    req = urllib.request.Request(
        f"{MOCK_DRIVE_BASE}/mock-drive/reset-delays",
        method="POST",
        data=b"{}",
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _backend_slides_current_slug() -> str | None:
    """Return the slug in /api/status slides_current, or None."""
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


# ── Parametrised test ────────────────────────────────────────────────────────
# Each row: (drive_delay_s, pptx_name, slug, host_slide, expected_participant_page)
# Different slugs → independent backend PDF cache entries, no cross-test pollution.
# expected_participant_page = host_slide because this is the participant's FIRST
# slides_current event (hostSlidesPrevious is null → follows current, not previous).

def _assert_follow_mode_active_and_on_page(pax_page, delay_s: int, slug: str, expected_page: int, pdf_ready_timeout_ms: int):
    """Wait for the PDF to render and assert follow mode + page are correct."""
    # #slides-page-inline shows "Page X/N" only after the PDF is fully loaded
    # and _syncSlidesPageControls has run with a live PdfViewer document.
    expect(pax_page.locator("#slides-page-inline")).to_contain_text(
        f"Page {expected_page}/",
        timeout=pdf_ready_timeout_ms,
    )
    print(f"[{delay_s}s] PDF rendered — page indicator shows 'Page {expected_page}/…'")

    # Follow mode must still be ENABLED.  If the bug is present, aria-pressed
    # flips to 'false' when updateviewarea fires after the suppression window expires.
    aria_pressed = pax_page.locator("#slides-follow-btn").get_attribute("aria-pressed")
    assert aria_pressed == "true", (
        f"[delay={delay_s}s] Follow mode was auto-disabled during slow PDF load! "
        f"Expected aria-pressed='true', got '{aria_pressed}'. "
        "Suppression window likely expired before pagesloaded."
    )
    print(f"[{delay_s}s] Follow mode still ACTIVE ✓")

    page_text = pax_page.locator("#slides-page-inline").inner_text()
    m = re.match(r"Page (\d+)/", page_text)
    assert m, f"Unexpected #slides-page-inline text: {page_text!r}"
    assert int(m.group(1)) == expected_page, (
        f"[delay={delay_s}s] Expected page {expected_page}, got {m.group(1)}"
    )
    print(f"[{delay_s}s] Participant is on page {expected_page} ✓")

    active_items = pax_page.locator(".slides-list-item.active")
    expect(active_items).to_have_count(1, timeout=3_000)
    active_id = active_items.first.get_attribute("data-slide-id") or ""
    assert slug in active_id, (
        f"[delay={delay_s}s] Active slide id '{active_id}' does not contain slug '{slug}'"
    )
    print(f"[{delay_s}s] Active slide '{active_id}' ✓")


@pytest.mark.nightly
@pytest.mark.parametrize("delay_s,presentation,slug,host_slide,expected_page", [
    (20, "Architecture.pptx",   "architecture",    2, 2),
], ids=["20s-delay"])
def test_follow_mode_survives_slow_drive(delay_s, presentation, slug, host_slide, expected_page):
    """
    Participant in follow mode eventually sees the correct slide page
    regardless of how long Google Drive takes to serve the PDF.
    Follow mode must NOT be disabled during the slow load.
    """
    _mock_drive_reset_delays()
    _mock_drive_set_delay(slug, delay_s)
    _clear_powerpoint_state()
    _set_powerpoint_state(presentation, host_slide)
    session_id = _create_session(f"SlowDrive-{delay_s}s")
    pdf_ready_timeout_ms = (delay_s + _ASSERT_BUFFER_S) * 1000

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            host_ctx = browser.new_context(
                http_credentials={"username": HOST_USER, "password": HOST_PASS}
            )
            host_page = host_ctx.new_page()
            host_page.goto(f"{BASE}/host/{session_id}", wait_until="networkidle")
            expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10_000)

            # Fresh browser context → localStorage empty → follow mode defaults to ON.
            pax_ctx = browser.new_context()
            pax_page = pax_ctx.new_page()
            pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
            pax = ParticipantPage(pax_page)
            pax.join(f"Follower-{delay_s}s")

            # Wait for daemon to push slides_current (probes every ~0.5s in tests).
            _await_condition(
                lambda: _backend_slides_current_slug() == slug,
                timeout_ms=15_000,
                msg=f"Daemon did not push slides_current for '{slug}' within 15s",
            )
            print(f"[{delay_s}s] Backend received slides_current slug='{slug}'")

            # Overlay opens as soon as auto-follow triggers (before PDF finishes).
            expect(pax_page.locator("#slides-overlay.open")).to_be_visible(timeout=15_000)
            print(f"[{delay_s}s] Overlay opened — Drive download starts (~{delay_s}s delay)")

            _assert_follow_mode_active_and_on_page(
                pax_page, delay_s, slug, expected_page, pdf_ready_timeout_ms,
            )
            print(f"✓ PASS [{delay_s}s delay]: follow mode survived slow PDF load")
            browser.close()

    finally:
        _clear_powerpoint_state()
        _mock_drive_reset_delays()
