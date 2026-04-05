"""
Hermetic E2E regression tests.

4 tests covering previously-reported regressions:
1. Auto-join with saved name causes no JS errors
2. Q&A action labels correct + edit with quotes works
3. QR fullscreen overlay opens/closes on click
4. Participant top header shows session name
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
from session_utils import fresh_session


BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:8081")
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


def _clear_qa(session_id: str) -> None:
    """Clear all Q&A questions via API (daemon endpoint)."""
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    req = urllib.request.Request(
        f"{DAEMON_BASE}/api/{session_id}/host/qa/clear",
        method="POST",
        headers={"Authorization": f"Basic {auth}", "Content-Length": "0"},
        data=b""
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
    host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
    expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10000)
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

        # Reload — should auto-join with saved name
        pax_page.reload(wait_until="networkidle")

        # Wait for main screen to appear (auto-join complete)
        expect(pax_page.locator("#main-screen")).to_be_visible(timeout=10000)

        # Allow time for any deferred JS to run
        pax_page.wait_for_timeout(2000)

        # Assert no JS errors occurred
        assert len(js_errors) == 0, f"JS errors during auto-join: {js_errors}"

        print("SUCCESS: Auto-join with saved name produces no JS errors!")
        browser.close()


# ── 2. Q&A action labels and edit with quotes ────────────────────────────

def test_qa_action_labels_and_edit_with_quotes():
    """Q&A host card has correct action labels; editing with quotes works."""
    session_id = fresh_session("QALabels")
    _clear_qa(session_id)  # isolate from previous test's Q&A state
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Open host first and switch to Q&A tab BEFORE participant joins
        # so participant's initial state fetch returns current_activity='qa'
        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10000)
        host = HostPage(host_page)
        host.open_qa_tab()

        # NOW participant joins — state fetch will return current_activity='qa'
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("QuoteTester")

        # Submit a question with quotes
        pax.submit_question('Could "quoted" text break edit?')

        # Wait for question to appear on host
        _await_condition(
            lambda: len(host.get_qa_questions()) > 0,
            timeout_ms=5000, msg="Host didn't see question"
        )
        questions = host.get_qa_questions()
        q = questions[0]
        card = host_page.locator(f'.qa-card[data-id="{q["id"]}"]')

        # Verify action button labels by reading innerHTML (avoids headless visibility issues
        # with overflow:hidden containers where buttons may be clipped but still in DOM)
        answer_btn = card.locator('button[onclick^="toggleAnswered"]')
        # Wait for the button to be in the DOM (attached)
        answer_btn.wait_for(state="attached", timeout=5000)
        answer_text = answer_btn.inner_text().strip()
        assert "Answer" in answer_text, f"Expected 'Answer' in button text, got: '{answer_text}'"

        delete_btn = card.locator(".btn-danger")
        delete_btn.wait_for(state="attached", timeout=5000)
        delete_text = delete_btn.inner_text().strip()
        assert "🗑" in delete_text, f"Expected '🗑' in delete button, got: '{delete_text}'"

        # Verify clear-all button (in tab-content-qa, always visible when qa tab is active)
        clear_btn = host_page.locator("#clear-qa-btn")
        expect(clear_btn).to_be_visible(timeout=3000)
        clear_text = clear_btn.inner_text().strip()
        assert "🗑 Delete all" in clear_text, f"Expected '🗑 Delete all', got: '{clear_text}'"

        # Edit the question to include quotes and apostrophes
        new_text = """What's the "best" approach — isn't it 'obvious'?"""
        host.edit_question(q["id"], new_text)

        # Verify the edited text appears correctly
        _await_condition(
            lambda: any(new_text in qq["text"] for qq in host.get_qa_questions()),
            timeout_ms=5000, msg="Edited text not visible on host"
        )

        # Verify participant also sees the edited text
        _await_condition(
            lambda: any(new_text in qq["text"] for qq in pax.get_qa_questions()),
            timeout_ms=5000, msg="Edited text not visible on participant"
        )

        print("SUCCESS: Q&A action labels correct and edit with quotes works!")
        browser.close()


# ── 3. QR fullscreen overlay opens/closes on click ───────────────────────

def test_qr_fullscreen_on_click():
    """Host QR icon opens fullscreen overlay; clicking dismisses it."""
    session_id = fresh_session("QROverlay")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10000)

        # Check QR icon exists and is visible
        qr_icon = host_page.locator("#footer-qr-icon")
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


# ── 4. Participant top header shows session name ──────────────────────────

def test_participant_header_shows_session_name():
    """Participant top header should display the current session name."""
    session_prefix = "SessionTitle"
    session_id = fresh_session(session_prefix)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")

        pax = ParticipantPage(pax_page)
        pax.auto_join()

        session_title = pax_page.locator("#session-title")
        expect(session_title).to_be_visible(timeout=10000)

        title_text = session_title.inner_text().strip()
        assert title_text, "Expected non-empty session title in participant header"
        assert session_prefix in title_text, (
            f"Expected participant header session title to contain '{session_prefix}', got: '{title_text}'"
        )

        print(f"SUCCESS: Participant header shows session title: {title_text!r}")
        browser.close()
