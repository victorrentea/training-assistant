"""
Hermetic E2E regression tests.

3 tests covering previously-reported regressions:
1. Auto-join with saved name causes no JS errors
2. QR fullscreen overlay opens/closes on click
3. Participant top header shows session name
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

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage
from playwright.sync_api import expect, sync_playwright
from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


def _await_condition(fn, timeout_ms=10000, poll_ms=300, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def _api_call(method, path, data=None, base=None):
    """Make API call. Defaults to DAEMON_BASE for host endpoints."""
    target = base or DAEMON_BASE
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    body = json.dumps(data).encode() if data else (b"" if method == "POST" else None)
    req = urllib.request.Request(
        f"{target}{path}", method=method,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        data=body,
    )
    if method == "POST" and data is None:
        req.add_header("Content-Length", "0")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _open_browser_trio(p, session_id):
    """Open host + participant browsers connected to a session."""
    browser = p.chromium.launch(headless=True)
    host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
    host_page = host_ctx.new_page()
    host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
    expect(host_page.locator("#tab-quiz")).to_be_visible(timeout=10000)
    host = HostPage(host_page)

    pax_ctx = browser.new_context()
    pax_page = pax_ctx.new_page()
    pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
    pax = ParticipantPage(pax_page)
    return browser, host, host_page, pax, pax_page


# ── 1. Auto-join with saved name causes no JS errors ─────────────────────

def test_autojoin_with_saved_name_no_js_error():
    """Participant with saved name + UUID in localStorage auto-joins without JS errors."""
    session_id = fresh_session("AutoJoin")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()

        # Pre-set localStorage with saved name and UUID before navigating
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax_page.evaluate("""() => {
            localStorage.setItem('workshop_participant_name', 'AutoJoiner');
            localStorage.setItem('workshop_participant_uuid', crypto.randomUUID());
        }""")

        # Register error listener BEFORE reload
        js_errors = []
        pax_page.on("pageerror", lambda err: js_errors.append(str(err)))

        # Reload — first-visit name gate appears (fresh UUID); Anonymous to enter.
        pax_page.reload(wait_until="networkidle")
        ParticipantPage(pax_page).dismiss_gate_anonymous()

        # Wait for display-name to appear (auto-join complete)
        expect(pax_page.locator("#display-name")).to_be_visible(timeout=10000)

        # Allow time for any deferred JS to run
        pax_page.wait_for_timeout(2000)

        # Assert no JS errors occurred
        assert len(js_errors) == 0, f"JS errors during auto-join: {js_errors}"

        print("SUCCESS: Auto-join with saved name produces no JS errors!")
        browser.close()


# ── 2. QR fullscreen overlay opens/closes on click ───────────────────────

def test_qr_fullscreen_on_click():
    """Host QR icon opens fullscreen overlay; clicking dismisses it."""
    session_id = fresh_session("QROverlay")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-quiz")).to_be_visible(timeout=10000)

        # Check QR icon exists and is visible
        qr_icon = host_page.locator("#top-qr-icon")
        expect(qr_icon).to_be_visible(timeout=5000)

        # Click QR icon → overlay should open
        qr_icon.click()
        qr_overlay = host_page.locator("#qr-overlay")
        expect(qr_overlay).to_have_class(re.compile(r"open"), timeout=5000)

        # Click inside the overlay (qr-fullscreen area) to dismiss
        host_page.locator("#qr-fullscreen").click()
        expect(qr_overlay).not_to_have_class(re.compile(r"open"), timeout=5000)

        print("SUCCESS: QR fullscreen overlay opens and closes on click!")
        browser.close()


# ── 3. Participant top header shows session name ──────────────────────────

def test_participant_header_shows_session_name():
    """Participant top header should display the current session name."""
    session_prefix = "SessionTitle"
    # fresh_session creates "x SessionTitle {ts}"; _applyState strips before first space
    # so displayed title becomes "SessionTitle {ts}" which contains session_prefix
    session_id = fresh_session(f"x {session_prefix}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")

        pax = ParticipantPage(pax_page)
        pax.auto_join()

        # Wait for state fetch / WS to deliver session_name (title is empty until then)
        pax_page.wait_for_function(
            f"() => {{ const el = document.getElementById('session-title'); return el && el.textContent.includes('{session_prefix}'); }}",
            timeout=10000,
        )

        session_title = pax_page.locator("#session-title")
        title_text = session_title.text_content().strip()
        assert title_text, "Expected non-empty session title in participant header"
        assert session_prefix in title_text, (
            f"Expected participant header session title to contain '{session_prefix}', got: '{title_text}'"
        )

        print(f"SUCCESS: Participant header shows session title: {title_text!r}")
        browser.close()
