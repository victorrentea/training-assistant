"""
Hermetic E2E test: Follow opens a slide not yet cached on Railway.

Root bug: Railway's proxy_to_daemon had a 5-second timeout. When a participant
clicked Follow on an uncached slide, the daemon's /check endpoint would trigger
a download from Google Drive but the Railway proxy would time out after 5s —
before the download completed — returning 503 to the participant.

Fix: proxy_to_daemon accepts a per-call timeout; the slides check endpoint
uses timeout=35s (5s buffer beyond the daemon's 30s download wait).

Tests:
  test_follow_opens_uncached_slide:
    8s Drive delay → exceeds old 5s proxy timeout, fits in new 35s limit.
    Participant in follow mode should see the slide load on the correct page.

  test_follow_retries_after_cache_status_event:
    32s Drive delay → exceeds daemon's 30s wait (returns 503). Railway finishes
    download in background. Daemon broadcasts slides_updated. Participant
    auto-retries and loads the slide.
"""

import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from playwright.sync_api import sync_playwright, expect

from pages.participant_page import ParticipantPage
from session_utils import fresh_session


BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
MOCK_DRIVE_BASE = f"http://localhost:{os.environ.get('MOCK_DRIVE_PORT', '9090')}"
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")
TRANSCRIPTION_FOLDER = Path(os.environ.get("TRANSCRIPTION_FOLDER", "/tmp/test-transcriptions"))


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


def _assert_follow_result(pax_page, slug: str, expected_page: int, timeout_ms: int):
    """Assert slides view open, correct slide active, correct page, follow still ON."""
    expect(pax_page.locator("#slides-view")).to_be_visible(timeout=timeout_ms)

    expect(pax_page.locator("#pdf-page-info")).to_contain_text(
        f"{expected_page} /",
        timeout=timeout_ms,
    )

    active_items = pax_page.locator(".topic-item.topic-active")
    expect(active_items).to_have_count(1, timeout=5_000)
    active_id = active_items.first.get_attribute("data-slide-id") or ""
    assert slug in active_id, f"Expected active slide to contain '{slug}', got '{active_id}'"

    is_checked = pax_page.locator("#slides-follow-checkbox").is_checked()
    assert is_checked, "Follow mode was disabled during load! slides-follow-checkbox is unchecked"

    page_text = pax_page.locator("#pdf-page-info").inner_text()
    m = re.match(r"(\d+) /", page_text)
    assert m, f"Unexpected #pdf-page-info text: {page_text!r}"
    assert int(m.group(1)) == expected_page, f"Expected page {expected_page}, got {m.group(1)}"


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.nightly
def test_follow_opens_uncached_slide():
    """
    Participant in follow mode loads a slide not yet cached on Railway.

    An 8-second Drive delay exceeds the old 5s proxy timeout but fits the
    new 35s limit. Before the fix the participant saw a 503 / error state.
    After the fix the slide loads at the host's current page.
    """
    DRIVE_DELAY_S = 8
    PRESENTATION = "Clean Code.pptx"
    SLUG = "clean-code"
    HOST_SLIDE = 5

    _mock_drive_reset_delays()
    _mock_drive_set_delay(SLUG, DRIVE_DELAY_S)
    _clear_slide_pointer()
    _set_slide_pointer(PRESENTATION, HOST_SLIDE)
    session_id = fresh_session("FollowUncached")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            host_ctx = browser.new_context(
                http_credentials={"username": HOST_USER, "password": HOST_PASS}
            )
            host_page = host_ctx.new_page()
            host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
            expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10_000)

            # Fresh context → empty localStorage → follow mode defaults to ON.
            pax_ctx = browser.new_context()
            pax_page = pax_ctx.new_page()
            pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
            pax = ParticipantPage(pax_page)
            pax.join("Follower-Uncached")

            # Wait for daemon to broadcast slides_current to backend.
            _await_condition(
                lambda: _backend_slides_current_slug() == SLUG,
                timeout_ms=15_000,
                msg=f"Daemon did not push slides_current for '{SLUG}' within 15s",
            )
            print(f"Backend slides_current slug='{SLUG}' ✓")

            # Follow auto-triggers on slides_current. Download takes ~{DRIVE_DELAY_S}s.
            # Old behaviour: proxy timed out at 5s → check returned 503 → nothing loaded.
            # New behaviour: proxy waits 35s → download completes → slide loads.
            _assert_follow_result(
                pax_page,
                slug=SLUG,
                expected_page=HOST_SLIDE,
                timeout_ms=(DRIVE_DELAY_S + 15) * 1000,
            )
            print(f"Slide '{SLUG}' page {HOST_SLIDE} loaded after {DRIVE_DELAY_S}s delay ✓")
            browser.close()

    finally:
        _clear_slide_pointer()
        _mock_drive_reset_delays()


@pytest.mark.nightly
def test_follow_retries_after_cache_status_event():
    """
    When the Drive delay exceeds the daemon's 30s check timeout (returns 503),
    the participant auto-retries once the background download completes and the
    daemon broadcasts slides_updated.

    Flow:
      1. Drive delay = 32s → /check returns 503 after 30s (daemon timeout)
      2. _pendingFollowRetry is set instead of showing a permanent error
      3. Remove the delay → Railway finishes the background download
      4. Daemon broadcasts slides_updated → participant re-queues follow
      5. Second /check → 200 → slide loads at host's current page
    """
    DRIVE_DELAY_S = 32        # beyond daemon's 30s wait
    PRESENTATION = "Clean Code.pptx"
    SLUG = "clean-code"
    HOST_SLIDE = 3
    REMOVE_DELAY_AFTER_S = 5  # seconds after /check starts to remove the delay

    _mock_drive_reset_delays()
    _mock_drive_set_delay(SLUG, DRIVE_DELAY_S)
    _clear_slide_pointer()
    _set_slide_pointer(PRESENTATION, HOST_SLIDE)
    session_id = fresh_session("FollowRetry")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            host_ctx = browser.new_context(
                http_credentials={"username": HOST_USER, "password": HOST_PASS}
            )
            host_page = host_ctx.new_page()
            host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
            expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10_000)

            pax_ctx = browser.new_context()
            pax_page = pax_ctx.new_page()
            pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
            pax = ParticipantPage(pax_page)
            pax.join("Follower-Retry")

            _await_condition(
                lambda: _backend_slides_current_slug() == SLUG,
                timeout_ms=15_000,
                msg=f"Daemon did not push slides_current for '{SLUG}' within 15s",
            )
            print(f"Backend slides_current slug='{SLUG}' ✓")

            # Wait a bit so the /check call has been issued, then remove the delay
            # so Railway can finish the background download it started.
            time.sleep(REMOVE_DELAY_AFTER_S)
            _mock_drive_reset_delays()
            print(f"Removed mock Drive delay after {REMOVE_DELAY_AFTER_S}s — background download will complete")

            # Daemon will eventually get pdf_download_complete and broadcast
            # slides_updated. Participant's handler will re-queue the follow.
            # Allow up to 60s for the retry cycle to complete.
            _assert_follow_result(
                pax_page,
                slug=SLUG,
                expected_page=HOST_SLIDE,
                timeout_ms=60_000,
            )
            print(f"Slide loaded after daemon-timeout retry ✓")
            browser.close()

    finally:
        _clear_slide_pointer()
        _mock_drive_reset_delays()
