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

import base64
import json
import os
import sys
import threading
import time
import urllib.request

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from pages.participant_page import ParticipantPage
from playwright.sync_api import expect, sync_playwright
from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")

_ADDON_BRIDGE_PORT = int(os.environ.get("WS_SERVER_PORT", "8765"))


def _auth_header() -> str:
    return "Basic " + base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()


def _prime_slide_cache(session_id: str, slug: str) -> None:
    """Warm Railway's PDF cache via the daemon /check endpoint.

    The first participant GET /api/slides can lose the proxy-hop race
    (PROXY_TIMEOUT=5s) on a cold cache, leaving the catalog empty so follow
    mode finds no target and /api/slides/download stays 404. Priming the
    deck up front makes the catalog warm and /download deterministically 200.
    """
    url = f"{DAEMON_BASE}/{session_id}/api/slides/check/{slug}?force=true"
    req = urllib.request.Request(url, headers={"Authorization": _auth_header()})
    with urllib.request.urlopen(req, timeout=35) as resp:
        assert resp.status == 200, f"/check for {slug} returned {resp.status}"


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


@pytest.mark.nightly
def test_follow_me_basic():
    """Participant clicks Follow → sees the host's current slide + page.

    Tagged nightly: the participant slide-follow cold-start path (catalog proxy
    hop + lazy Drive download) is timing-flaky under the hermetic harness
    (intermittent proxy timeouts / mock-Drive 502s). It is exercised in the
    nightly build; the every-push hermetic job excludes it to stay deterministic.
    """
    session_id = fresh_session("FollowMe")

    # Prime the deck the host is presenting so the catalog is warm and
    # /api/slides/download serves a 200 before the follow assertions run.
    _prime_slide_cache(session_id, "clean-code")

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
        pax_page.on("console", lambda m: print(f"[DIAG console] {m.type}: {m.text}"))
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

        # DIAG: instrument _onFollowChange to count invocations + values
        pax_page.evaluate("""() => {
            window._followCalls = [];
            const orig = window._onFollowChange;
            window._onFollowChange = function(checked) {
                window._followCalls.push({checked: checked, cbState: (document.getElementById('slides-follow-checkbox')||{}).checked});
                return orig.apply(this, arguments);
            };
        }""")

        # DIAG: capture-phase click logger + label geometry/hit-test
        pax_page.evaluate("""() => {
            document.addEventListener('click', (e) => {
                const t = e.target;
                console.log('[DIAG clicktarget] tag=' + t.tagName + ' id=' + t.id
                    + ' for=' + (t.getAttribute && t.getAttribute('for'))
                    + ' cls=' + ((t.className||'').toString().slice(0,50)));
            }, true);
        }""")
        rect_info = pax_page.evaluate("""() => {
            const lbl = document.querySelector('label[for="slides-follow-checkbox"]');
            if (!lbl) return {err:'no label'};
            const r = lbl.getBoundingClientRect();
            const cx = Math.round(r.left + r.width/2), cy = Math.round(r.top + r.height/2);
            const at = document.elementFromPoint(cx, cy);
            return {rect:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)},
                    center:{cx,cy},
                    atTag: at && at.tagName, atId: at && at.id,
                    atFor: at && at.getAttribute && at.getAttribute('for'),
                    atCls: at && (at.className||'').toString().slice(0,50)};
        }""")
        print(f"[DIAG rect] {json.dumps(rect_info, default=str)}")

        # Click the Follow button (label for the checkbox)
        follow_btn = pax_page.locator("label[for='slides-follow-checkbox']")
        follow_btn.wait_for(state="visible", timeout=5000)
        follow_btn.click()
        print("Clicked Follow button")
        diag_click = pax_page.evaluate("""() => ({
            followCalls: window._followCalls,
            cbCheckedNow: (document.getElementById('slides-follow-checkbox')||{}).checked,
        })""")
        print(f"[DIAG click] {json.dumps(diag_click, default=str)}")

        # The slides view should become visible
        expect(pax_page.locator("#slides-view")).to_be_visible(timeout=10000)
        print("Slides view opened")

        time.sleep(3)
        diag = pax_page.evaluate("""() => ({
            followChecked: (document.getElementById('slides-follow-checkbox')||{}).checked,
            followEnabled: (typeof _isSlidesFollowEnabled==='function') ? _isSlidesFollowEnabled() : 'n/a',
            slidesViewSelected: (typeof _isSlidesViewSelected==='function') ? _isSlidesViewSelected() : 'n/a',
            catalogLen: (typeof _slidesCatalog!=='undefined') ? _slidesCatalog.length : 'n/a',
            catalogSlugs: (typeof _slidesCatalog!=='undefined') ? _slidesCatalog.map(s=>s.slug) : 'n/a',
            activeSlideId: (typeof _activeSlideId!=='undefined') ? _activeSlideId : 'n/a',
            hostCurrent: (typeof _hostSlidesCurrent!=='undefined') ? _hostSlidesCurrent : 'n/a',
            topicItemCount: document.querySelectorAll('.topic-item').length,
            topicItemIds: Array.from(document.querySelectorAll('.topic-item')).map(n=>n.getAttribute('data-slide-id')),
            topicActiveCount: document.querySelectorAll('.topic-item.topic-active').length,
            hasMarkActive: typeof _markActiveTopic,
        })""")
        print(f"[DIAG state] {json.dumps(diag, default=str)}")

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
