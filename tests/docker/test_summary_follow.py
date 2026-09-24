"""
Hermetic E2E test: participants follow the host's scroll through the Summary.

The host reads the summary on the participant page of the host machine
(ON_HOST_MACHINE cookie). Its scroll is POSTed to the daemon's loopback
/summary/scroll, broadcast as `summary_scroll`, and every follower scrolls to
the same bullet — at a different width and with its own bullets collapsed.

Flow:
1. Host and participant (different viewport widths) open the Summary.
2. Host scrolls to Topic 25 → participant lands on Topic 25.
3. Host expands Topic 30 and scrolls into its 2nd sub-bullet → the participant,
   who has Topic 30 collapsed, lands on Topic 30.
4. A late joiner lands on the host's bullet from /state alone.
5. Participant on another tab: Summary nav blinks; opening it lands on the host.
6. Participant scrolls with the wheel → Follow unticks; host moves → participant stays;
   🎯 jumps once; re-ticking Follow lands on the host again.
7. The summary is rewritten (new block keys) → following still works.

The host page's loopback call is proxied by Playwright: the test page is served
from localhost:8000, which the daemon's CORS policy (prod origin only) rejects.
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
from pages.participant_page import ParticipantPage
from playwright.sync_api import expect, sync_playwright
from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
SESSIONS_FOLDER = os.environ.get("SESSIONS_FOLDER", "/tmp/test-sessions")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


def _await_condition(fn, timeout_ms=8000, poll_ms=200, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def _get_active_session_name(session_id: str) -> str | None:
    try:
        auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
        req = urllib.request.Request(
            f"{DAEMON_BASE}/api/{session_id}/host/state",
            headers={"Authorization": f"Basic {auth}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read()).get("daemon_session_folder")
    except Exception:
        return None


def _write_long_summary(session_name: str, revision: str = "") -> None:
    """80 top-level bullets, every 5th with three sub-bullets, under a heading."""
    lines = ["# Workshop summary", ""]
    for i in range(1, 81):
        lines.append(f"- Topic {i}: a point long enough to wrap on a narrow screen, "
                     f"so the two viewports lay it out at different heights.{revision}")
        if i % 5 == 0:
            for j in range(1, 4):
                lines.append(f"    - Detail {i}.{j} explaining the point in more depth.")
    folder = os.path.join(SESSIONS_FOLDER, session_name)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "ai-summary.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


# Distance (px) from the reading line (top of the text area) to the bullet whose
# own text starts with `prefix`. 0 = that bullet is exactly where the host reads.
_OFFSET_JS = """(prefix) => {
  const sc = document.getElementById('summary-scroll');
  const line = sc.getBoundingClientRect().top + parseFloat(getComputedStyle(sc).paddingTop);
  const li = [...document.querySelectorAll('#summary-content li')]
    .find(l => (l.firstChild && l.firstChild.textContent || '').trim().startsWith(prefix));
  return li ? li.getBoundingClientRect().top - line : null;
}"""

_SCROLL_TO_JS = """(prefix) => {
  const sc = document.getElementById('summary-scroll');
  const line = sc.getBoundingClientRect().top + parseFloat(getComputedStyle(sc).paddingTop);
  const li = [...document.querySelectorAll('#summary-content li')]
    .find(l => (l.firstChild && l.firstChild.textContent || '').trim().startsWith(prefix));
  sc.scrollTop += li.getBoundingClientRect().top - line;
}"""


def _await_sent(host, pred, msg: str) -> None:
    """Wait for the host to report a position. Pumps the host page while waiting:
    a bare sleep starves Playwright's route handler, so nothing would be sent."""
    for _ in range(30):
        if pred():
            return
        host.wait_for_timeout(100)
    raise AssertionError(msg)


def _at(page, prefix: str) -> bool:
    off = page.evaluate(_OFFSET_JS, prefix)
    return off is not None and abs(off) <= 4


def _open_summary(page) -> None:
    page.locator('[data-nav="summary"]').click()
    expect(page.locator("#summary-content li").first).to_be_visible(timeout=8000)


# The "available only during the training" toast appears outside work hours and
# sits over the Summary toolbar; pre-dismiss it so the result can't depend on the clock.
_NO_ACCESS_TOAST_JS = """(() => { const d = new Date();
  const day = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  localStorage.setItem('new:access_toast_dismissed_date', day); })()"""


def _new_context(browser, width: int, height: int = 800):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    ctx.add_init_script(_NO_ACCESS_TOAST_JS)
    return ctx


def _new_participant(browser, width: int):
    ctx = _new_context(browser, width)
    page = ctx.new_page()
    return ctx, page


@pytest.mark.nightly
def test_participants_follow_host_summary_scroll():
    session_id = fresh_session("SummaryFollow")
    session_name = _await_condition(
        lambda: _get_active_session_name(session_id), timeout_ms=5000,
        msg="Could not get active session name from daemon",
    )
    _write_long_summary(session_name)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ── Host: the participant page on the host machine ──
        host_ctx = _new_context(browser, 1600, 700)
        host_ctx.add_cookies([{"name": "ON_HOST_MACHINE", "value": "true", "url": BASE}])
        sent = []

        def _proxy_loopback(route):
            req = route.request
            if req.url.endswith("/summary/scroll") and req.method == "POST":
                sent.append(json.loads(req.post_data))
                body = req.post_data.encode()
                fwd = urllib.request.Request(
                    f"{DAEMON_BASE}/summary/scroll", data=body, method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(fwd, timeout=5) as resp:
                    route.fulfill(status=resp.status, body=resp.read(),
                                  headers={"Access-Control-Allow-Origin": "*"})
            else:
                route.abort()   # trainer claim / session switch: not under test

        host_ctx.route("http://127.0.0.1:1234/**", _proxy_loopback)
        host = host_ctx.new_page()
        host.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        ParticipantPage(host).join("Trainer")

        pax_ctx, pax = _new_participant(browser, 1024)
        pax.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        ParticipantPage(pax).join("Reader")

        expect(pax.locator('[data-nav="summary"]')).to_be_visible(timeout=8000)
        _open_summary(host)
        _open_summary(pax)

        # Follow controls: shown and ticked for participants, absent on the host.
        expect(pax.locator("#summary-follow-controls")).to_be_visible()
        assert pax.locator("#summary-follow-checkbox").is_checked()
        expect(host.locator("#summary-follow-controls")).to_be_hidden()
        print("Step 1 OK: follow controls on participant only, ticked by default")

        # ── Step 2: host scrolls to Topic 25 ──
        host.evaluate(_SCROLL_TO_JS, "Topic 25:")
        _await_condition(lambda: _at(pax, "Topic 25:"), timeout_ms=5000,
                         msg=f"participant did not land on Topic 25 "
                             f"(offset={pax.evaluate(_OFFSET_JS, 'Topic 25:')}, sent={sent[-1:]})")
        print("Step 2 OK: participant followed the host to Topic 25 at another width")

        # ── Step 3: host is inside a bullet the participant has collapsed ──
        host.locator("#summary-content li", has_text="Topic 30:").locator(".sum-toggle").first.click()
        host.evaluate(_SCROLL_TO_JS, "Detail 30.2")
        _await_sent(host, lambda: sent and sent[-1]["path"] == [29, 1],
                    msg=f"host did not report the sub-bullet: {sent[-1:]}")
        _await_condition(lambda: _at(pax, "Topic 30:"), timeout_ms=5000,
                         msg=f"participant did not land on collapsed Topic 30 "
                             f"(offset={pax.evaluate(_OFFSET_JS, 'Topic 30:')})")
        print("Step 3 OK: a collapsed participant lands on the parent bullet")

        # ── Step 4: late joiner lands there from /state ──
        host.evaluate(_SCROLL_TO_JS, "Topic 12:")
        _await_condition(lambda: _at(pax, "Topic 12:"), timeout_ms=5000,
                         msg="participant did not follow to Topic 12")
        late_ctx, late = _new_participant(browser, 1280)
        late.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        ParticipantPage(late).join("Late")
        _open_summary(late)
        _await_condition(lambda: _at(late, "Topic 12:"), timeout_ms=5000,
                         msg=f"late joiner did not land on Topic 12 "
                             f"(offset={late.evaluate(_OFFSET_JS, 'Topic 12:')})")
        late_ctx.close()
        print("Step 4 OK: a late joiner lands on the host's bullet")

        # ── Step 5: participant on another tab ──
        pax.evaluate("showView('activity')")
        host.evaluate(_SCROLL_TO_JS, "Topic 33:")
        expect(pax.locator('[data-nav="summary"]')).to_have_class(
            re.compile(r"summary-nav-blink"), timeout=5000)
        _open_summary(pax)
        _await_condition(lambda: _at(pax, "Topic 33:"), timeout_ms=5000,
                         msg="reopening Summary did not land on Topic 33")
        expect(pax.locator('[data-nav="summary"]')).not_to_have_class(
            re.compile(r"summary-nav-blink"))
        print("Step 5 OK: nav blinks off-tab; reopening Summary lands on the host")

        # ── Step 5b: pinch-zoom (ctrl+wheel) is not "scrolling away" ──
        pax.locator("#summary-scroll").hover()
        pax.keyboard.down("Control")
        pax.mouse.wheel(0, -100)
        pax.keyboard.up("Control")
        pax.wait_for_timeout(500)
        assert pax.locator("#summary-follow-checkbox").is_checked(), "zooming must not untick Follow"
        _await_condition(lambda: _at(pax, "Topic 33:"), timeout_ms=5000,
                         msg=f"zoom reflow was not re-landed on Topic 33 "
                             f"(offset={pax.evaluate(_OFFSET_JS, 'Topic 33:')})")
        print("Step 5b OK: zoom keeps Follow and re-lands on the host's bullet")

        # ── Step 6: participant scrolls by hand → stops following ──
        pax.locator("#summary-scroll").hover()
        pax.mouse.wheel(0, -600)
        expect(pax.locator("#summary-follow-checkbox")).not_to_be_checked(timeout=2000)
        pax.wait_for_timeout(500)
        own_scroll = pax.evaluate("document.getElementById('summary-scroll').scrollTop")
        host.evaluate(_SCROLL_TO_JS, "Topic 3:")
        _await_sent(host, lambda: sent and sent[-1]["path"] == [2],
                    msg=f"host did not report Topic 3: {sent[-1:]}")
        pax.wait_for_timeout(1000)
        assert pax.evaluate("document.getElementById('summary-scroll').scrollTop") == own_scroll, \
            "an unticked participant must stay where they scrolled"
        # 🎯 jumps to the host once, without re-ticking Follow.
        pax.locator("#summary-follow-controls button").click()
        _await_condition(lambda: _at(pax, "Topic 3:"), timeout_ms=5000,
                         msg="🎯 did not jump to Topic 3")
        assert not pax.locator("#summary-follow-checkbox").is_checked()
        pax.mouse.wheel(0, 900)
        pax.wait_for_timeout(500)
        # Ticking Follow again lands back on the host.
        pax.locator('label[for="summary-follow-checkbox"]').click()
        _await_condition(lambda: _at(pax, "Topic 3:"), timeout_ms=5000,
                         msg="re-ticking Follow did not land on Topic 3")
        print("Step 6 OK: own scroll unticks Follow; re-ticking lands on the host")

        # ── Step 7: the summariser rewrites the file — block keys change ──
        old_key = sent[-1]["block_key"]
        _write_long_summary(session_name, revision=" (revised)")
        _await_sent(host, lambda: sent[-1]["block_key"] != old_key,
                    msg=f"host did not re-report under the new block key: {sent[-1:]}")
        host.evaluate(_SCROLL_TO_JS, "Topic 20:")
        _await_condition(lambda: _at(pax, "Topic 20:"), timeout_ms=8000,
                         msg=f"participant did not follow after the rewrite "
                             f"(offset={pax.evaluate(_OFFSET_JS, 'Topic 20:')}, sent={sent[-1:]})")
        print("Step 7 OK: following survives a summary rewrite")

        browser.close()
