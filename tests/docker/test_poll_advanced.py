"""
Hermetic E2E tests: advanced poll features.

6 tests covering multi-select scoring, correct_count hints, and timer behavior:
1. Correct count hint shown to participant
2. Multi-select scoring — all correct
3. Multi-select scoring — partial (1 correct + 1 wrong) → zero
4. Multi-select scoring — all wrong → zero
5. Timer countdown visible
6. Timer cleared on poll close
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


# ── 1. Correct count hint shown to participant ────────────────────────────

def test_correct_count_hint_shown_to_participant():
    """Multi-select poll with correct_count=2 → participant sees 'exactly 2' hint."""
    session_id = _create_session("CorrectCountHint")
    with sync_playwright() as p:
        browser, host, host_page, pax, pax_page = _open_browser_trio(p, session_id)
        expect(host_page.locator("#ws-badge.connected")).to_be_visible(timeout=10000)
        pax.join("Hinter")

        host.create_poll(
            "Pick 2 correct answers:",
            ["Alpha", "Beta", "Gamma", "Delta"],
            multi=True, correct_count=2,
        )

        # Wait for poll to appear on participant
        expect(pax_page.locator(".option-btn").first).to_be_visible(timeout=5000)

        # The vote-msg area should contain "exactly 2"
        vote_msg = pax_page.locator(".vote-msg")
        expect(vote_msg).to_be_visible(timeout=5000)
        expect(vote_msg).to_contain_text("exactly 2", timeout=5000)

        print("SUCCESS: Correct count hint shown to participant!")
        browser.close()


# ── 2. Multi-select scoring — all correct ─────────────────────────────────

def test_multi_select_scoring_all_correct():
    """Vote for both correct options in multi-select → score >= 400."""
    session_id = _create_session("MultiAllCorrect")
    with sync_playwright() as p:
        browser, host, host_page, pax, pax_page = _open_browser_trio(p, session_id)
        expect(host_page.locator("#ws-badge.connected")).to_be_visible(timeout=10000)
        pax.join("AllCorrect")

        host.create_poll(
            "Which are OOP?",
            ["Encapsulation", "Polymorphism", "Gravity", "Spaghetti"],
            multi=True, correct_count=2,
        )

        expect(pax_page.locator(".option-btn").first).to_be_visible(timeout=5000)
        pax.multi_vote("Encapsulation", "Polymorphism")

        # Verify 2 selected
        expect(pax_page.locator(".option-btn.selected")).to_have_count(2, timeout=3000)

        host.close_poll()
        host.mark_correct("Encapsulation", "Polymorphism")

        _await_condition(
            lambda: pax.get_score() > 0,
            timeout_ms=5000, msg="Participant did not receive score for all-correct multi-select"
        )
        score = pax.get_score()
        print(f"Score after all-correct multi-select: {score}")
        assert score >= 400, f"Expected score >= 400, got {score}"

        print("SUCCESS: Multi-select all correct scoring works!")
        browser.close()


# ── 3. Multi-select scoring — partial (1 correct + 1 wrong) → zero ───────

def test_multi_select_scoring_partial_zero():
    """Vote 1 correct + 1 wrong in multi-select → score == 0."""
    session_id = _create_session("MultiPartial")
    with sync_playwright() as p:
        browser, host, host_page, pax, pax_page = _open_browser_trio(p, session_id)
        expect(host_page.locator("#ws-badge.connected")).to_be_visible(timeout=10000)
        pax.join("PartialVoter")

        host.create_poll(
            "Which are OOP?",
            ["Encapsulation", "Polymorphism", "Gravity", "Spaghetti"],
            multi=True, correct_count=2,
        )

        expect(pax_page.locator(".option-btn").first).to_be_visible(timeout=5000)
        # Vote 1 correct (Encapsulation) + 1 wrong (Gravity)
        pax.multi_vote("Encapsulation", "Gravity")

        expect(pax_page.locator(".option-btn.selected")).to_have_count(2, timeout=3000)

        host.close_poll()
        host.mark_correct("Encapsulation", "Polymorphism")

        # Wait for scoring to propagate
        pax_page.wait_for_timeout(2000)
        score = pax.get_score()
        print(f"Score after partial multi-select (1 correct + 1 wrong): {score}")
        assert score == 0, f"Expected score == 0 for partial answer, got {score}"

        print("SUCCESS: Multi-select partial answer gives zero score!")
        browser.close()


# ── 4. Multi-select all wrong → zero score ────────────────────────────────

def test_multi_select_all_wrong_zero_score():
    """Vote 2 wrong options in multi-select → score == 0."""
    session_id = _create_session("MultiAllWrong")
    with sync_playwright() as p:
        browser, host, host_page, pax, pax_page = _open_browser_trio(p, session_id)
        expect(host_page.locator("#ws-badge.connected")).to_be_visible(timeout=10000)
        pax.join("WrongVoter")

        host.create_poll(
            "Which are OOP?",
            ["Encapsulation", "Polymorphism", "Gravity", "Spaghetti"],
            multi=True, correct_count=2,
        )

        expect(pax_page.locator(".option-btn").first).to_be_visible(timeout=5000)
        # Vote 2 wrong options
        pax.multi_vote("Gravity", "Spaghetti")

        expect(pax_page.locator(".option-btn.selected")).to_have_count(2, timeout=3000)

        host.close_poll()
        host.mark_correct("Encapsulation", "Polymorphism")

        # Wait for scoring to propagate
        pax_page.wait_for_timeout(2000)
        score = pax.get_score()
        print(f"Score after all-wrong multi-select: {score}")
        assert score == 0, f"Expected score == 0 for all-wrong answer, got {score}"

        print("SUCCESS: Multi-select all wrong gives zero score!")
        browser.close()


# ── 5. Timer countdown visible ────────────────────────────────────────────

def test_timer_countdown_visible():
    """Start a 10s timer → participant sees countdown with 's' in text."""
    session_id = _create_session("TimerVisible")
    with sync_playwright() as p:
        browser, host, host_page, pax, pax_page = _open_browser_trio(p, session_id)
        expect(host_page.locator("#ws-badge.connected")).to_be_visible(timeout=10000)
        pax.join("TimerWatcher")

        host.create_poll("Timed question?", ["A", "B", "C"])

        # Wait for poll to appear on participant
        expect(pax_page.locator(".option-btn").first).to_be_visible(timeout=5000)

        # Start a 10-second timer via API
        _api_call("POST", f"/api/{session_id}/poll/timer", {"seconds": 10})

        # Participant should see countdown element with text containing "s"
        countdown = pax_page.locator("#pax-countdown")
        _await_condition(
            lambda: countdown.inner_text().strip() != "" and "s" in countdown.inner_text(),
            timeout_ms=5000,
            msg="Countdown text not visible or doesn't contain 's'"
        )
        countdown_text = countdown.inner_text().strip()
        print(f"Countdown text: '{countdown_text}'")
        assert "s" in countdown_text, f"Expected 's' in countdown text, got '{countdown_text}'"

        print("SUCCESS: Timer countdown visible!")
        browser.close()


# ── 6. Timer cleared on poll close ────────────────────────────────────────

def test_timer_cleared_on_close():
    """Start timer → verify visible → close poll → timer text cleared."""
    session_id = _create_session("TimerClear")
    with sync_playwright() as p:
        browser, host, host_page, pax, pax_page = _open_browser_trio(p, session_id)
        expect(host_page.locator("#ws-badge.connected")).to_be_visible(timeout=10000)
        pax.join("TimerClearer")

        host.create_poll("Timer clear test?", ["X", "Y", "Z"])

        expect(pax_page.locator(".option-btn").first).to_be_visible(timeout=5000)

        # Start timer
        _api_call("POST", f"/api/{session_id}/poll/timer", {"seconds": 30})

        # Verify countdown is active
        countdown = pax_page.locator("#pax-countdown")
        _await_condition(
            lambda: countdown.inner_text().strip() != "" and "s" in countdown.inner_text(),
            timeout_ms=5000,
            msg="Countdown not active before close"
        )
        print(f"Countdown before close: '{countdown.inner_text().strip()}'")

        # Close the poll via API — the "Close voting" button is hidden while timer is active
        _api_call("PUT", f"/api/{session_id}/poll/status", {"open": False})

        # Timer should be cleared (empty text or element gone)
        _await_condition(
            lambda: countdown.count() == 0 or countdown.inner_text().strip() == ""
                    or "s" not in countdown.inner_text(),
            timeout_ms=5000,
            msg="Countdown still showing after poll close"
        )
        print(f"Countdown after close: '{countdown.inner_text().strip()}'")

        print("SUCCESS: Timer cleared on poll close!")
        browser.close()
