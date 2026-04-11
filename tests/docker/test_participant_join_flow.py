"""
Hermetic E2E tests: participant join flow — all branches.

Covers every screen in the landing page join flow:
1. /api/is-active-session endpoint (active / inactive)
2. is-active-session retry behaviour (active → code entry, inactive → error)
3. Code entry (Case A): valid code redirects, invalid code shows toast
4. Session mismatch (Case B): stale session_id, clear link
5. Name entry: custom name, random name, duplicate name, disabled button
6. Rejoin: returning participant auto-enters with stored UUID
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from playwright.sync_api import sync_playwright, expect

from session_utils import (
    BASE,
    DAEMON_BASE,
    HOST_USER,
    HOST_PASS,
    fresh_session,
    daemon_has_participant,
    _get_json,
    _req,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pw():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def browser(pw):
    b = pw.chromium.launch(headless=True)
    yield b
    b.close()


@pytest.fixture
def session_id():
    return fresh_session("JoinFlow")


# ── Helpers ─────────────────────────────────────────────────────────────────

def _open_landing(browser, query=""):
    """Open the landing page in a fresh context. Returns (ctx, page)."""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{BASE}/{query}", wait_until="networkidle")
    return ctx, page


def _end_session():
    """End the current daemon session."""
    try:
        _req("POST", f"{DAEMON_BASE}/api/session/end")
    except Exception:
        pass
    # Wait for daemon to confirm empty
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        data = _get_json(f"{DAEMON_BASE}/api/session/active")
        if data.get("session_id") is None:
            return
        time.sleep(0.3)


# ── 1. TestIsActiveSessionEndpoint ──────────────────────────────────────────

class TestIsActiveSessionEndpoint:
    def test_returns_true_when_session_active(self, session_id):
        """GET /api/is-active-session returns {active: true} when a session is running."""
        data = _get_json(f"{BASE}/api/is-active-session")
        assert data.get("active") is True, f"Expected active=true, got {data}"

    def test_returns_false_when_no_session(self, session_id):
        """GET /api/is-active-session returns {active: false} when no session is running."""
        _end_session()
        try:
            data = _get_json(f"{BASE}/api/is-active-session")
            assert data.get("active") is False, f"Expected active=false, got {data}"
        finally:
            # Restore a session for subsequent tests
            fresh_session("JoinFlowRestore")


# ── 2. TestIsActiveSessionCheck ─────────────────────────────────────────────

class TestIsActiveSessionCheck:
    def test_active_session_shows_code_entry(self, browser, session_id):
        """When session is active and no session_id param, landing shows code input."""
        ctx, page = _open_landing(browser)
        try:
            screen = page.locator("#screen-code-entry")
            expect(screen).to_be_visible(timeout=10000)
            expect(page.locator("#code-input")).to_be_visible()
        finally:
            ctx.close()

    @pytest.mark.nightly
    def test_no_active_session_shows_error(self, browser, session_id):
        """When no session running, retries exhaust and shows 'No session started'."""
        _end_session()
        try:
            ctx, page = _open_landing(browser)
            try:
                error_screen = page.locator("#screen-error")
                expect(error_screen).to_be_visible(timeout=30000)
                error_title = page.locator("#error-title")
                expect(error_title).to_contain_text("No session started", timeout=30000)
            finally:
                ctx.close()
        finally:
            fresh_session("JoinFlowRestore")


# ── 3. TestCodeEntry (Case A) ──────────────────────────────────────────────

class TestCodeEntry:
    def test_valid_code_redirects(self, browser, session_id):
        """Entering a valid 6-char code redirects to ?session_id={code}."""
        ctx, page = _open_landing(browser)
        try:
            expect(page.locator("#screen-code-entry")).to_be_visible(timeout=10000)
            code_input = page.locator("#code-input")
            code_input.fill(session_id)
            # Auto-submits on 6 chars — wait for navigation to name entry or entering
            page.wait_for_url(f"**/?session_id={session_id}", timeout=10000)
            # After redirect, should proceed to name entry screen
            expect(page.locator("#screen-name-entry")).to_be_visible(timeout=10000)
        finally:
            ctx.close()

    def test_invalid_code_shows_error(self, browser, session_id):
        """Entering an invalid 6-char code shows toast 'Invalid session code'."""
        ctx, page = _open_landing(browser)
        try:
            expect(page.locator("#screen-code-entry")).to_be_visible(timeout=10000)
            code_input = page.locator("#code-input")
            code_input.fill("zzzzzz")
            # Wait for toast
            toaster = page.locator("#toaster")
            expect(toaster).to_have_class(re.compile(r"visible"), timeout=5000)
            expect(toaster).to_contain_text("Invalid session code")
        finally:
            ctx.close()


# ── 4. TestSessionMismatch (Case B) ────────────────────────────────────────

class TestSessionMismatch:
    def test_stale_session_id_shows_mismatch(self, browser, session_id):
        """Wrong session_id in URL shows 'Session not started' mismatch screen."""
        ctx, page = _open_landing(browser, "?session_id=badcod")
        try:
            mismatch = page.locator("#screen-mismatch")
            expect(mismatch).to_be_visible(timeout=10000)
            expect(mismatch).to_contain_text("Session not started")
        finally:
            ctx.close()

    def test_mismatch_clear_link_goes_to_code_entry(self, browser, session_id):
        """Clicking 'enter another session id' clears param and shows code entry."""
        ctx, page = _open_landing(browser, "?session_id=badcod")
        try:
            mismatch = page.locator("#screen-mismatch")
            expect(mismatch).to_be_visible(timeout=10000)
            link = mismatch.locator("a.landing-mismatch-link")
            expect(link).to_be_visible()
            link.click()
            # Should navigate to / (no session_id) and show code entry
            page.wait_for_url("**/", timeout=10000)
            expect(page.locator("#screen-code-entry")).to_be_visible(timeout=10000)
        finally:
            ctx.close()


# ── 5. TestNameEntry ───────────────────────────────────────────────────────

class TestNameEntry:
    def _go_to_name_entry(self, browser, session_id):
        """Navigate directly to landing with valid session_id to reach name entry."""
        ctx, page = _open_landing(browser, f"?session_id={session_id}")
        expect(page.locator("#screen-name-entry")).to_be_visible(timeout=10000)
        return ctx, page

    def test_valid_session_shows_name_entry(self, browser, session_id):
        """Valid session_id in URL leads to name entry screen."""
        ctx, page = self._go_to_name_entry(browser, session_id)
        try:
            expect(page.locator("#name-input")).to_be_visible()
            expect(page.locator("#name-join-btn")).to_be_visible()
            expect(page.locator("#random-name-btn")).to_be_visible()
        finally:
            ctx.close()

    def test_submit_custom_name_enters_app(self, browser, session_id):
        """Submitting a custom name navigates to /{session_id} app."""
        ctx, page = self._go_to_name_entry(browser, session_id)
        try:
            name_input = page.locator("#name-input")
            join_btn = page.locator("#name-join-btn")
            name_input.fill("CustomTestUser")
            expect(join_btn).to_be_enabled()
            join_btn.click()
            # Should navigate to /{session_id} and show main screen
            page.wait_for_url(f"**/{session_id}", timeout=10000)
            expect(page.locator("#main-screen")).to_be_visible(timeout=10000)
        finally:
            ctx.close()

    def test_random_name_enters_app(self, browser, session_id):
        """Clicking 'Random name' enters the app with a server-assigned name."""
        ctx, page = self._go_to_name_entry(browser, session_id)
        try:
            random_btn = page.locator("#random-name-btn")
            random_btn.click()
            # Should navigate to /{session_id} and show main screen
            page.wait_for_url(f"**/{session_id}", timeout=10000)
            expect(page.locator("#main-screen")).to_be_visible(timeout=10000)
        finally:
            ctx.close()

    def test_duplicate_name_shakes_input(self, browser, session_id):
        """Submitting a taken name shows 'Name taken' toast and stays on name screen."""
        # First participant takes a name
        ctx1, page1 = self._go_to_name_entry(browser, session_id)
        try:
            page1.locator("#name-input").fill("TakenName")
            page1.locator("#name-join-btn").click()
            page1.wait_for_url(f"**/{session_id}", timeout=10000)
            expect(page1.locator("#main-screen")).to_be_visible(timeout=10000)
        finally:
            ctx1.close()

        # Second participant tries the same name
        ctx2, page2 = self._go_to_name_entry(browser, session_id)
        try:
            page2.locator("#name-input").fill("TakenName")
            page2.locator("#name-join-btn").click()
            # Should show toast and stay on name screen
            toaster = page2.locator("#toaster")
            expect(toaster).to_have_class(re.compile(r"visible"), timeout=5000)
            expect(toaster).to_contain_text("Name taken")
            expect(page2.locator("#screen-name-entry")).to_be_visible()
        finally:
            ctx2.close()

    def test_join_button_disabled_when_empty(self, browser, session_id):
        """Join button is disabled when name input is empty or whitespace."""
        ctx, page = self._go_to_name_entry(browser, session_id)
        try:
            join_btn = page.locator("#name-join-btn")
            name_input = page.locator("#name-input")
            # Initially disabled
            expect(join_btn).to_be_disabled()
            # Type whitespace only — still disabled
            name_input.fill("   ")
            expect(join_btn).to_be_disabled()
            # Type real text — enabled
            name_input.fill("RealName")
            expect(join_btn).to_be_enabled()
            # Clear — disabled again
            name_input.fill("")
            expect(join_btn).to_be_disabled()
        finally:
            ctx.close()


# ── 6. TestRejoin ──────────────────────────────────────────────────────────

class TestRejoin:
    def test_returning_participant_auto_enters(self, browser, session_id):
        """Participant with stored UUID+custom name auto-enters on second visit."""
        # First visit: join with a custom name
        ctx1 = browser.new_context()
        page1 = ctx1.new_page()
        try:
            page1.goto(f"{BASE}/?session_id={session_id}", wait_until="networkidle")
            expect(page1.locator("#screen-name-entry")).to_be_visible(timeout=10000)
            page1.locator("#name-input").fill("RejoinerTest")
            page1.locator("#name-join-btn").click()
            page1.wait_for_url(f"**/{session_id}", timeout=10000)
            expect(page1.locator("#main-screen")).to_be_visible(timeout=10000)

            # Grab the UUID and custom-name flag from localStorage
            uuid = page1.evaluate("() => localStorage.getItem('workshop_participant_uuid')")
            custom_flag = page1.evaluate("() => localStorage.getItem('workshop_custom_name')")
            stored_name = page1.evaluate("() => localStorage.getItem('workshop_participant_name')")
            assert uuid, "UUID should be stored in localStorage"
            assert custom_flag == "1", "Custom name flag should be '1'"
        finally:
            ctx1.close()

        # Second visit: new context but inject the same UUID + flags into localStorage
        ctx2 = browser.new_context()
        page2 = ctx2.new_page()
        try:
            # Navigate to landing first to set localStorage on the correct origin
            page2.goto(f"{BASE}/", wait_until="networkidle")
            page2.evaluate(f"""() => {{
                localStorage.setItem('workshop_participant_uuid', '{uuid}');
                localStorage.setItem('workshop_custom_name', '1');
                localStorage.setItem('workshop_participant_name', '{stored_name}');
            }}""")
            # Now navigate to the session landing
            page2.goto(f"{BASE}/?session_id={session_id}", wait_until="networkidle")
            # Should auto-enter without showing name screen
            page2.wait_for_url(f"**/{session_id}", timeout=10000)
            expect(page2.locator("#main-screen")).to_be_visible(timeout=10000)
        finally:
            ctx2.close()
