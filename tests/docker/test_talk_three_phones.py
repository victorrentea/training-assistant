"""
Hermetic E2E: a conference talk watched by several phones at once.

Real backend + real daemon in one container; a mock addon bridge plays the
trainer's PowerPoint (it pushes `slide_presenting_now` events) and the desktop
emoji overlay (it records the daemon's `display_emoji` messages).

Three phones of different shapes (two portrait, one landscape) follow the
trainer slide by slide; a fourth joins late; one scrolls away and pauses; all of
them send emoji, which reach the overlay only while the host's ❤️ master switch
is on. No phone is ever asked for a name.

Set TALK_SCREENSHOT_DIR to keep a screenshot of every phone at the end.

Tagged nightly: the daemon's bridge client reconnects every 5s, so the test
cannot stay under the every-push 5s budget.
"""

import asyncio
import base64
import json
import os
import queue
import sys
import threading
import time
import urllib.request

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from playwright.sync_api import expect, sync_playwright
from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")
_ADDON_BRIDGE_PORT = int(os.environ.get("WS_SERVER_PORT", "8765"))
DECK = "Design Patterns.pptx"  # 8-page fixture PDF, slug design-patterns

PHONES = {
    "portrait": {"width": 390, "height": 844},
    "small": {"width": 375, "height": 667},
    "landscape": {"width": 844, "height": 390},
}


class _MockAddonBridge:
    """Plays PowerPoint (pushes slide events) and the overlay (records display_emoji)."""

    def __init__(self):
        self.events: queue.Queue = queue.Queue()
        self.connected = threading.Event()
        self.displayed: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=lambda: asyncio.run(self._serve()), daemon=True)

    async def _serve(self):
        import websockets

        async def handle(websocket):
            self.connected.set()

            async def read():
                async for raw in websocket:
                    msg = json.loads(raw)
                    if msg.get("type") == "display_emoji":
                        self.displayed.append(msg.get("emoji"))

            reader = asyncio.ensure_future(read())
            loop = asyncio.get_running_loop()
            try:
                while not self._stop.is_set():
                    try:
                        evt = await loop.run_in_executor(None, self.events.get, True, 0.2)
                    except queue.Empty:
                        continue
                    await websocket.send(json.dumps(evt))
            finally:
                reader.cancel()

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


def _toggle_emoji_master(session_id: str) -> bool:
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    req = urllib.request.Request(
        f"{DAEMON_BASE}/api/{session_id}/host/emoji/global-toggle",
        method="POST", data=b"", headers={"Authorization": f"Basic {auth}"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())["emoji_global_enabled"]


def _wait(fn, timeout=10.0, msg="condition not met"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return
        time.sleep(0.2)
    raise AssertionError(msg)


def _all_in_view(pages: dict, slide: int, timeout_ms: int = 15_000):
    for name, page in pages.items():
        try:
            page.wait_for_function(_IN_VIEW_JS, arg=slide, timeout=timeout_ms)
        except Exception as exc:
            raise AssertionError(f"phone '{name}' never showed slide {slide}") from exc


@pytest.mark.nightly
def test_three_phones_follow_the_talk_and_react():
    session_id = fresh_session("TalkThreePhones", session_type="talk")

    with _MockAddonBridge() as bridge, sync_playwright() as p:
        assert bridge.connected.wait(timeout=15), "daemon addon-bridge client never connected"
        browser = p.chromium.launch(headless=True)

        pages = {}
        for name, viewport in PHONES.items():
            ctx = browser.new_context(viewport=viewport, is_mobile=True, has_touch=True)
            page = ctx.new_page()
            page.goto(f"{BASE}/{session_id}/")
            pages[name] = page
        for page in pages.values():
            # Straight in from the QR code: no name prompt, no desktop warning.
            expect(page.locator("#emoji-bar")).to_be_visible(timeout=10_000)
            expect(page.locator("#desktop-warning")).to_be_hidden()
            expect(page.locator("input")).to_have_count(0)

        # ── The trainer jumps around the deck; every phone follows ─────────────
        for slide in (3, 7, 5):
            bridge.present(slide)
            _all_in_view(pages, slide, timeout_ms=30_000 if slide == 3 else 15_000)
        bridge.present(3)  # back to an earlier slide: scrolled to, never duplicated
        _all_in_view(pages, 3)
        for name, page in pages.items():
            assert page.evaluate(_SHOWN_ORDER_JS) == [3, 7, 5], name
            # Following: the "Current Slide" button stays out of the way.
            expect(page.locator("#fab-current-slide")).to_be_hidden()

        # In landscape the slide fits whole between the two side columns.
        # (Waited for: the scroll to the revisited slide is smooth.)
        fit_js = """() => {
          const v = document.getElementById('view-slides').getBoundingClientRect();
          const c = document.querySelector('#pdf-pages section[data-page="3"] .slide-img').getBoundingClientRect();
          return c.top >= v.top - 1 && c.bottom <= v.bottom + 1 && c.left >= v.left - 1 && c.right <= v.right + 1;
        }"""
        try:
            pages["landscape"].wait_for_function(fit_js, timeout=5_000)
        except Exception as exc:
            geo = pages["landscape"].evaluate("""() => {
              const r = (el) => { const b = el.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom].map(Math.round); };
              return {view: r(document.getElementById('view-slides')),
                      slide: r(document.querySelector('#pdf-pages section[data-page="3"] .slide-img'))};
            }""")
            raise AssertionError(f"landscape slide does not fit inside the slides view: {geo}") from exc

        # Two more new slides: the live one is now last in the list, far from the top.
        for slide in (6, 4):
            bridge.present(slide)
            _all_in_view(pages, slide)

        # ── A latecomer lands on the live slide ─────────────────────────────────
        late_ctx = browser.new_context(viewport=PHONES["portrait"], is_mobile=True, has_touch=True)
        late = late_ctx.new_page()
        late.goto(f"{BASE}/{session_id}/")
        late.wait_for_function(_IN_VIEW_JS, arg=4, timeout=15_000)
        assert late.evaluate(_SHOWN_ORDER_JS) == [4]

        # The audience count reaches every phone (throttled, but final value delivered).
        for page in [*pages.values(), late]:
            expect(page.locator("#pax-count")).to_have_text("4", timeout=10_000)

        # ── One reader scrolls back to the first slide and pauses; the others keep following
        reader = pages["small"]
        reader.locator("#view-slides").dispatch_event("touchmove")
        reader.evaluate("() => document.getElementById('view-slides').scrollTo({ top: 0, behavior: 'instant' })")
        _wait(lambda: reader.evaluate("() => window._following === false"), msg="manual scroll did not pause follow")
        expect(reader.locator("#fab-current-slide")).to_be_visible()

        bridge.present(8)
        _all_in_view({k: v for k, v in pages.items() if k != "small"}, 8)
        late.wait_for_function(_IN_VIEW_JS, arg=8, timeout=15_000)
        reader.wait_for_function(
            "() => !!document.querySelector('#pdf-pages section[data-page=\"8\"] .slide-img')", timeout=15_000)
        assert not reader.evaluate(_IN_VIEW_JS, 8), "paused reader was moved to the live slide"
        reader.locator("#fab-current-slide button").click()
        reader.wait_for_function(_IN_VIEW_JS, arg=8, timeout=10_000)
        expect(reader.locator("#fab-current-slide")).to_be_hidden()

        # ── Emoji reach the trainer's overlay, and the ❤️ switch stops them ──────
        everyone = {**pages, "late": late}
        before = len(bridge.displayed)
        for page in everyone.values():
            page.locator("#emoji-bar button").first.click()
        _wait(lambda: len(bridge.displayed) >= before + len(everyone), msg="emoji did not reach the overlay")
        # Talk mode: the cumulative counter shows up on every phone.
        for page in everyone.values():
            expect(page.locator("#emoji-bar button").first.locator(".emoji-count")).to_have_text(
                str(len(everyone)), timeout=5_000)

        assert _toggle_emoji_master(session_id) is False
        before = len(bridge.displayed)
        for page in everyone.values():
            page.locator("#emoji-bar button").nth(1).click()
        time.sleep(2.5)
        assert len(bridge.displayed) == before, "emoji reached the overlay with the master switch OFF"

        assert _toggle_emoji_master(session_id) is True
        pages["portrait"].locator("#emoji-bar button").nth(2).click()
        _wait(lambda: len(bridge.displayed) == before + 1, msg="emoji did not come back after switch ON")

        shots = os.environ.get("TALK_SCREENSHOT_DIR")
        if shots:
            os.makedirs(shots, exist_ok=True)
            for name, page in everyone.items():
                page.screenshot(path=os.path.join(shots, f"phone-{name}.png"))

        browser.close()
