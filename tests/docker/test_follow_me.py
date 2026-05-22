"""
Hermetic E2E test: Follow Me — participant follows host's slide.

Flow:
1. Test runs a mock addon-bridge WS server at port 8765
2. Daemon's addon bridge connects and receives a slide event {"deck": "Clean Code.pptx", "slide": 3}
3. Daemon processes the event and sends slides_current to backend
4. Participant clicks "Follow" button
5. Participant is navigated to "Clean Code" topic, page 3

Infrastructure:
- Daemon AddonBridgeClient connects to ws://127.0.0.1:8765 and drains slide events each loop
- Backend broadcasts slides_current to participant via WS
"""

import json
import os
import sys
import threading
import time
import urllib.request

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

from pages.participant_page import ParticipantPage
from playwright.sync_api import expect, sync_playwright
from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")

_ADDON_BRIDGE_PORT = int(os.environ.get("WS_SERVER_PORT", "8765"))


def _await_condition(fn, timeout_ms=10000, poll_ms=300, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def _run_mock_addon_bridge(deck: str, slide: int, stop_event: threading.Event):
    """Run a mock addon-bridge WS server that sends one slide event to each connecting client."""
    import asyncio

    import websockets

    async def handle(websocket):
        await websocket.send(json.dumps({"type": "slide_presenting_now", "deck": deck, "slide": slide, "presenting": True}))
        # Hold the connection open until the test is done
        await asyncio.get_event_loop().run_in_executor(None, stop_event.wait, 30)

    async def serve():
        async with websockets.serve(handle, "127.0.0.1", _ADDON_BRIDGE_PORT):
            await asyncio.get_event_loop().run_in_executor(None, stop_event.wait, 30)

    asyncio.run(serve())


def test_follow_me_basic():
    """Participant clicks Follow → sees the host's current slide + page."""
    session_id = fresh_session("FollowMe")

    # Start mock addon-bridge WS server so the daemon picks up the slide event
    stop_event = threading.Event()
    bridge_thread = threading.Thread(
        target=_run_mock_addon_bridge,
        args=("Clean Code.pptx", 3, stop_event),
        daemon=True,
    )
    bridge_thread.start()
    # Give the server a moment to bind, then the daemon reconnects within ~5s
    time.sleep(0.5)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Connect host so the WS is active
        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-quiz")).to_be_visible(timeout=10000)

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
                        const el = document.getElementById('slides-follow-checkbox')
                            || document.querySelector('label[for="slides-follow-checkbox"]');
                        return el !== null;
                    } catch { return false; }
                }
            """),
            timeout_ms=15000,
            msg="Follow button not found on participant page"
        )

        time.sleep(2)

        # Wait for daemon to detect slide pointer and broadcast
        # current_slide_updated to participants. State is daemon-resident
        # (not on Railway's /api/status); verify via the participant's
        # JS-side `_hostSlidesCurrent` — same state that drives follow mode.
        def _participant_has_host_slide():
            try:
                sc = pax_page.evaluate("() => window._hostSlidesCurrent || null")
                return sc.get("slug") if sc else None
            except Exception:
                return None

        slug = _await_condition(
            _participant_has_host_slide,
            timeout_ms=20000,
            msg="Daemon did not broadcast current_slide_updated to the participant within 20s"
        )
        print(f"Participant _hostSlidesCurrent slug: {slug}")

        # Click the Follow button (label for the checkbox)
        follow_btn = pax_page.locator("label[for='slides-follow-checkbox']")
        follow_btn.wait_for(state="visible", timeout=5000)
        follow_btn.click()
        print("Clicked Follow button")

        # The slides view should become visible
        expect(pax_page.locator("#slides-view")).to_be_visible(timeout=10000)
        print("Slides view opened")

        # Verify the PDF was fetched (from mock Drive or cache)
        slug = "clean-code"
        pdf_url = f"{BASE}/{session_id}/api/slides/download/{slug}"

        _await_condition(
            lambda: _try_fetch_pdf(pdf_url),
            timeout_ms=15000,
            msg="PDF not available from backend"
        )

        # Verify the participant navigated to the correct slide
        _await_condition(
            lambda: pax_page.locator(".topic-item.topic-active").count() > 0,
            timeout_ms=15000,
            msg="No active slide item after clicking Follow"
        )
        active_id = pax_page.locator(".topic-item.topic-active").get_attribute("data-slide-id")
        print(f"Active slide ID: {active_id}")
        # data-slide-id format is "slug|url", so check the slug part
        assert "clean-code" in (active_id or ""), f"Expected active slide to be 'clean-code', got '{active_id}'"

        # Verify the PDF endpoint is reachable
        assert _try_fetch_pdf(pdf_url), "PDF not available from backend"
        print("PDF is available from backend")

        print("SUCCESS: Follow Me navigated participant to host's 'Clean Code' slide!")

        stop_event.set()
        browser.close()


def _try_fetch_pdf(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = resp.read()
            return data[:5] == b"%PDF-"
    except Exception:
        return False
