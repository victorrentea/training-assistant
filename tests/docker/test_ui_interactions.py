"""
Hermetic E2E tests: UI interaction scenarios.

3 tests covering host UI edge cases:
1. Host tab survives reload
2. QR code rendered
3. Participant link displayed
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
from session_utils import fresh_session, daemon_has_participant


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
    """Make API call. Defaults to BASE (Railway). Pass base=DAEMON_BASE for daemon endpoints."""
    target = base or BASE
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


# ── 1. Host tab survives reload ───────────────────────────────────────────

def test_host_tab_survives_reload():
    """Switch to Q&A tab, reload page, Q&A tab should still be active."""
    session_id = fresh_session("TabReload")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_page)

        # Switch to Q&A tab
        host.open_qa_tab()

        # Verify Q&A tab is active
        expect(host_page.locator("#tab-qa.active")).to_be_visible(timeout=3000)

        # Reload the page
        host_page.reload(wait_until="networkidle")
        expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10000)

        # After reload, check if Q&A tab is still active
        # The active tab is determined by the server's current_activity state
        # Since host opened Q&A (which sets activity to qa), it should persist
        _await_condition(
            lambda: host_page.locator("#tab-qa.active").is_visible(),
            timeout_ms=5000,
            msg="Q&A tab not active after reload"
        )

        print("SUCCESS: Host tab survives reload!")
        browser.close()


# ── 2. QR code rendered ──────────────────────────────────────────────────

def test_qr_code_rendered():
    """Host page should render a QR code."""
    session_id = fresh_session("QRCode")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10000)

        # Wait for QR code to render
        host_page.wait_for_timeout(2000)

        # Check for QR code canvas or img inside #qr-code or #center-qr
        qr_exists = host_page.evaluate("""() => {
            const containers = ['qr-code', 'center-qr', 'conference-qr-code'];
            for (const id of containers) {
                const el = document.getElementById(id);
                if (el) {
                    const canvas = el.querySelector('canvas');
                    const img = el.querySelector('img');
                    if (canvas || img) return true;
                }
            }
            return false;
        }""")
        assert qr_exists, "QR code canvas/img not found in any QR container"

        print("SUCCESS: QR code rendered!")
        browser.close()


# ── 3. Participant link displayed ─────────────────────────────────────────

def test_participant_link_displayed():
    """Host page should show a participant link."""
    session_id = fresh_session("PaxLink")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10000)

        # Wait for WS to deliver state
        host_page.wait_for_timeout(1000)

        # Check participant-link element
        link_el = host_page.locator("#participant-link")
        expect(link_el).to_be_visible(timeout=5000)

        link_text = link_el.inner_text().strip()
        assert len(link_text) > 0, f"Participant link text is empty"
        # Should contain session_id or a URL-like string
        print(f"Participant link text: '{link_text}'")

        print("SUCCESS: Participant link displayed!")
        browser.close()
