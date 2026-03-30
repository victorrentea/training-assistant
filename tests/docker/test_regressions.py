"""
Hermetic E2E regression tests.

3 tests covering previously-reported regressions:
1. Auto-join with saved name causes no JS errors
2. Q&A action labels correct + edit with quotes works
3. QR fullscreen overlay opens/closes on click
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


BASE = "http://localhost:8000"
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


def _api_call(method, path, data=None):
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    body = json.dumps(data).encode() if data else (b"" if method == "POST" else None)
    req = urllib.request.Request(
        f"{BASE}{path}", method=method,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        data=body,
    )
    if method == "POST" and data is None:
        req.add_header("Content-Length", "0")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _create_session(name="Test", session_type="workshop") -> str:
    """Create a fresh session via API — gives clean state."""
    result = _api_call("POST", "/api/session/create", {"name": f"{name} {int(time.time())}", "type": session_type})
    return result["session_id"]


def _open_browser_trio(p, session_id):
    """Open host + participant browsers connected to a session."""
    browser = p.chromium.launch(headless=True)
    host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
    host_page = host_ctx.new_page()
    host_page.goto(f"{BASE}/host/{session_id}", wait_until="networkidle")
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
    session_id = _create_session("AutoJoin")
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
    session_id = _create_session("QALabels")
    with sync_playwright() as p:
        browser, host, host_page, pax, pax_page = _open_browser_trio(p, session_id)
        pax.join("QuoteTester")
        host.open_qa_tab()

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

        # Verify action button labels
        answer_btn = card.locator('button[onclick^="toggleAnswered"]')
        expect(answer_btn).to_be_visible(timeout=3000)
        answer_text = answer_btn.inner_text().strip()
        assert "Answer" in answer_text, f"Expected 'Answer' in button text, got: '{answer_text}'"

        delete_btn = card.locator(".btn-danger")
        expect(delete_btn).to_be_visible(timeout=3000)
        delete_text = delete_btn.inner_text().strip()
        assert "🗑" in delete_text, f"Expected '🗑' in delete button, got: '{delete_text}'"

        # Verify clear-all button
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
    session_id = _create_session("QROverlay")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_page = host_ctx.new_page()
        host_page.goto(f"{BASE}/host/{session_id}", wait_until="networkidle")
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
