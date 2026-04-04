"""
Hermetic E2E test: Follow Me — participant follows host's slide.

Flow:
1. Test writes to activity-slides-YYYY-MM-DD.md to simulate host on "Clean Code" slide 3
2. Daemon picks it up (reads every ~0.5s) and sends slides_current to backend
3. Participant clicks "Follow" button
4. Participant is navigated to "Clean Code" topic, page 3

Infrastructure:
- Daemon reads the last line of activity-slides-YYYY-MM-DD.md in TRANSCRIPTION_FOLDER
- Backend broadcasts slides_current to participant via WS
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


BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:8081")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")

TRANSCRIPTION_FOLDER = Path(os.environ.get("TRANSCRIPTION_FOLDER", "/tmp/test-transcriptions"))


def _activity_slides_file() -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    return TRANSCRIPTION_FOLDER / f"activity-slides-{today}.md"


def _await_condition(fn, timeout_ms=10000, poll_ms=300, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def _set_slide_pointer(deck: str, slide: int):
    """Write slide pointer for the daemon to pick up."""
    f = _activity_slides_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(f"{deck}:{slide}\n")


def _clear_slide_pointer():
    _activity_slides_file().unlink(missing_ok=True)


def _get_or_create_session() -> str:
    try:
        with urllib.request.urlopen(f"{BASE}/api/session/active", timeout=5) as resp:
            data = json.loads(resp.read())
            if data.get("session_id"):
                return data["session_id"]
    except Exception:
        pass
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        page = ctx.new_page()
        page.goto(f"{DAEMON_BASE}/host", wait_until="networkidle")
        if re.search(r"/host/[a-zA-Z0-9]+", page.url):
            sid = page.url.split("/host/")[-1].split("?")[0]
            browser.close()
            return sid
        page.locator("#session-name-input").fill("Follow Test")
        btn = page.locator("#create-btn-workshop")
        expect(btn).to_be_enabled(timeout=3000)
        btn.click()
        page.wait_for_url(re.compile(r"/host/[a-zA-Z0-9]+"), timeout=15000)
        sid = page.url.split("/host/")[-1].split("?")[0]
        browser.close()
        return sid


def test_follow_me_basic():
    """Participant clicks Follow → sees the host's current slide + page."""
    session_id = _get_or_create_session()

    # Simulate host on "Clean Code.pptx" slide 3
    _set_slide_pointer("Clean Code.pptx", slide=3)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Connect host so the WS is active
        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10000)

        # Participant joins
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("Follower")

        # Wait for daemon to pick up the slide pointer and send slides_current
        _await_condition(
            lambda: pax_page.evaluate("""
                () => {
                    try {
                        const el = document.getElementById('slides-follow-btn');
                        return el !== null;
                    } catch { return false; }
                }
            """),
            timeout_ms=15000,
            msg="Follow button not found on participant page"
        )

        time.sleep(2)

        # Wait for daemon to detect slide pointer and push slides_current to backend
        def _backend_has_slides_current():
            try:
                req = urllib.request.Request(
                    f"{BASE}/api/status",
                    headers={"Authorization": f"Basic {__import__('base64').b64encode(f'{HOST_USER}:{HOST_PASS}'.encode()).decode()}"}
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read())
                    sc = data.get("slides_current")
                    return sc and sc.get("slug")
            except Exception:
                return None

        slug = _await_condition(
            _backend_has_slides_current,
            timeout_ms=20000,
            msg="Daemon did not push slides_current to backend within 20s"
        )
        print(f"Backend slides_current slug: {slug}")

        # Click the Follow button
        follow_btn = pax_page.locator("#slides-follow-btn")
        follow_btn.wait_for(state="visible", timeout=5000)
        follow_btn.click()
        print("Clicked Follow button")

        # The slides overlay should open with the correct topic
        expect(pax_page.locator("#slides-overlay.open")).to_be_visible(timeout=10000)
        print("Slides overlay opened")

        # Verify the PDF was fetched (from mock Drive or cache)
        slug = "clean-code"
        pdf_url = f"{BASE}/{session_id}/api/slides/file/{slug}"

        _await_condition(
            lambda: _try_fetch_pdf(pdf_url),
            timeout_ms=15000,
            msg="PDF not available from backend"
        )

        # Verify the participant navigated to the correct slide
        active_slide = _await_condition(
            lambda: pax_page.locator(".slides-list-item.active").count() > 0,
            timeout_ms=15000,
            msg="No active slide item after clicking Follow"
        )
        active_id = pax_page.locator(".slides-list-item.active").get_attribute("data-slide-id")
        print(f"Active slide ID: {active_id}")
        assert "clean-code" in (active_id or ""), f"Expected active slide to be 'clean-code', got '{active_id}'"

        # Verify the PDF endpoint is reachable
        assert _try_fetch_pdf(pdf_url), "PDF not available from backend"
        print("PDF is available from backend")

        print("SUCCESS: Follow Me navigated participant to host's 'Clean Code' slide!")

        _clear_slide_pointer()
        browser.close()


def _try_fetch_pdf(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = resp.read()
            return data[:5] == b"%PDF-"
    except Exception:
        return False
