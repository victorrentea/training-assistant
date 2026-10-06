"""
Hermetic E2E test: the conference talk page (static/talk.html) follows the trainer.

Flow:
1. A fresh session of type "talk" makes Railway serve talk.html at /{session_id}/.
2. The test runs a mock addon-bridge WS server (port 8765); the daemon's bridge
   client connects to it and receives `slide_presenting_now` events, which the
   daemon turns into `current_slide_updated` broadcasts.
3. The phone-sized talk page must add each shown slide (in the order first shown,
   never twice) and scroll to it — with no name prompt anywhere — and its emoji
   bar must only send reactions the daemon accepts.

Tagged nightly: the daemon's bridge client reconnects every 5s, so the test
cannot stay under the every-push 5s budget.
"""

import asyncio
import json
import os
import queue
import sys
import threading

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from playwright.sync_api import expect, sync_playwright
from session_utils import fresh_session

BASE = "http://localhost:8000"
_ADDON_BRIDGE_PORT = int(os.environ.get("WS_SERVER_PORT", "8765"))
DECK = "Design Patterns.pptx"  # 8-page fixture PDF, slug design-patterns


class _MockAddonBridge:
    """WS server the daemon's addon-bridge client connects to; pushes queued slide events."""

    def __init__(self):
        self.events: queue.Queue = queue.Queue()
        self.connected = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=lambda: asyncio.run(self._serve()), daemon=True)

    async def _serve(self):
        import websockets

        async def handle(websocket):
            self.connected.set()
            loop = asyncio.get_running_loop()
            while not self._stop.is_set():
                try:
                    evt = await loop.run_in_executor(None, self.events.get, True, 0.2)
                except queue.Empty:
                    continue
                await websocket.send(json.dumps(evt))

        async with websockets.serve(handle, "127.0.0.1", _ADDON_BRIDGE_PORT):
            while not self._stop.is_set():
                await asyncio.sleep(0.2)

    def present(self, slide: int):
        self.events.put({"type": "slide_presenting_now", "deck": DECK, "slide": slide, "presenting": True})

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=5)


_IN_VIEW_JS = """(n) => {
  const s = document.querySelector('#pdf-pages section[data-page="' + n + '"]');
  if (!s || !s.querySelector('.slide-img')) return false;
  const v = document.getElementById('view-slides').getBoundingClientRect();
  const r = s.getBoundingClientRect();
  return Math.min(r.bottom, v.bottom) - Math.max(r.top, v.top) >= 0.5 * Math.min(r.height, v.height);
}"""
_SHOWN_ORDER_JS = "() => [...document.querySelectorAll('#pdf-pages section')].map(s => +s.dataset.page)"


@pytest.mark.nightly
def test_talk_page_follows_the_trainer_slide_by_slide():
    session_id = fresh_session("TalkFollow", session_type="talk")

    with _MockAddonBridge() as bridge, sync_playwright() as p:
        assert bridge.connected.wait(timeout=15), "daemon addon-bridge client never connected"
        browser = p.chromium.launch(headless=True)
        phone = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = phone.new_page()
        page.goto(f"{BASE}/{session_id}/")

        # Railway serves the talk page for a talk session; nobody is asked for a name.
        expect(page.locator("#emoji-bar")).to_be_visible(timeout=10_000)
        expect(page.locator("#desktop-warning")).to_be_hidden()
        expect(page.locator("input")).to_have_count(0)

        bridge.present(3)
        page.wait_for_function(_IN_VIEW_JS, arg=3, timeout=30_000)

        bridge.present(7)
        page.wait_for_function(_IN_VIEW_JS, arg=7, timeout=15_000)

        # Back to an already shown slide: scrolled to, never duplicated.
        bridge.present(3)
        page.wait_for_function(_IN_VIEW_JS, arg=3, timeout=15_000)
        assert page.evaluate(_SHOWN_ORDER_JS) == [3, 7]

        # The emoji bar only offers reactions the daemon accepts (no 400s).
        with page.expect_response(lambda r: "/api/participant/emoji/reaction" in r.url) as resp:
            page.locator("#emoji-bar button").first.click()
        assert resp.value.status == 204, resp.value.status

        browser.close()
