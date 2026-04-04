"""
Hermetic E2E tests: UI interaction scenarios.

10 tests covering participant/host UI edge cases:
1. Already-upvoted button disabled
2. No JS errors on wordcloud submit
3. Special chars in wordcloud
4. Late joiner sees wordcloud
5. Leaderboard shows personal rank
6. Escape closes all participant modals
7. Host tab survives reload
8. QR code rendered
9. Participant link displayed
10. Poll download captures two polls
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


def _create_session(name="Test", session_type="workshop") -> str:
    """Create a fresh session via API — gives clean state."""
    result = _api_call("POST", "/api/session/create", {"name": f"{name} {int(time.time())}", "type": session_type})
    return result["session_id"]


# ── 1. Already-upvoted button disabled ────────────────────────────────────

def test_already_upvoted_button_disabled():
    """P1 submits question, P2 upvotes it → P2's upvote button is disabled with qa-upvoted class."""
    session_id = _create_session("UpvoteDisabled")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Host opens Q&A
        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_page)
        host.open_qa_tab()

        # P1 joins and submits a question
        pax1_ctx = browser.new_context()
        pax1_page = pax1_ctx.new_page()
        pax1_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax1 = ParticipantPage(pax1_page)
        pax1.join("Asker")
        pax1.submit_question("What is dependency injection?")

        # P2 joins
        pax2_ctx = browser.new_context()
        pax2_page = pax2_ctx.new_page()
        pax2_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax2 = ParticipantPage(pax2_page)
        pax2.join("Voter")

        # Wait for question to appear on P2
        _await_condition(
            lambda: len(pax2.get_qa_questions()) > 0,
            timeout_ms=5000, msg="P2 didn't see the question"
        )

        # P2 upvotes the question
        questions = pax2.get_qa_questions()
        q_id = questions[0]["id"]
        pax2.upvote_question(q_id)

        # Wait for upvote to register
        pax2_page.wait_for_timeout(1000)

        # Verify P2's upvote button is disabled and has qa-upvoted class
        upvote_btn = pax2_page.locator(f'.qa-upvote-btn[data-qid="{q_id}"]')
        btn_class = upvote_btn.get_attribute("class") or ""
        assert "qa-upvoted" in btn_class, f"Expected 'qa-upvoted' in class, got: '{btn_class}'"
        assert upvote_btn.is_disabled(), "Upvote button should be disabled after upvoting"

        print("SUCCESS: Already-upvoted button disabled!")
        browser.close()


# ── 2. No JS errors on wordcloud submit ──────────────────────────────────

def test_wordcloud_no_js_errors_on_submit():
    """Submit a word to wordcloud — no JS errors should fire."""
    session_id = _create_session("WCNoErrors")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Host opens wordcloud
        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_page)
        host.open_wordcloud_tab()

        # Participant joins
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()

        # Register JS error listener BEFORE navigating
        js_errors = []
        pax_page.on("pageerror", lambda err: js_errors.append(str(err)))

        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("WordSubmitter")

        # Wait for wordcloud to appear
        expect(pax_page.locator("#wc-canvas")).to_be_visible(timeout=5000)

        # Submit a word
        pax.submit_word("resilience")
        pax_page.wait_for_timeout(1000)

        assert len(js_errors) == 0, f"JS errors detected: {js_errors}"

        print("SUCCESS: No JS errors on wordcloud submit!")
        browser.close()


# ── 3. Special chars in wordcloud ─────────────────────────────────────────

def test_special_chars_in_wordcloud():
    """Submit 'cafe' with accent → appears in my words list."""
    session_id = _create_session("WCSpecial")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Host opens wordcloud
        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_page)
        host.open_wordcloud_tab()

        # Participant joins
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("AccentUser")

        expect(pax_page.locator("#wc-canvas")).to_be_visible(timeout=5000)

        pax.submit_word("café")

        _await_condition(
            lambda: "café" in pax.get_wordcloud_my_words(),
            timeout_ms=5000, msg="'café' not found in my words"
        )

        print("SUCCESS: Special chars in wordcloud!")
        browser.close()


# ── 4. Late joiner sees wordcloud ─────────────────────────────────────────

def test_late_joiner_sees_wordcloud():
    """Host opens wordcloud, then a NEW participant joins → sees #wc-canvas visible."""
    session_id = _create_session("WCLateJoin")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Host opens wordcloud
        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_page)
        host.open_wordcloud_tab()

        # Wait a moment for activity to propagate
        host_page.wait_for_timeout(500)

        # NOW a new participant joins
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("LateCloud")

        # Late joiner should see the wordcloud canvas
        expect(pax_page.locator("#wc-canvas")).to_be_visible(timeout=5000)

        print("SUCCESS: Late joiner sees wordcloud!")
        browser.close()


# ── 5. Leaderboard shows personal rank ────────────────────────────────────

def test_leaderboard_shows_personal_rank():
    """P1 submits 2 questions (200pts), P2 submits 1 (100pts). Leaderboard show → both see overlay."""
    session_id = _create_session("LeaderRank")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Host opens Q&A
        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_page)
        host.open_qa_tab()

        # P1 joins and submits 2 questions
        pax1_ctx = browser.new_context()
        pax1_page = pax1_ctx.new_page()
        pax1_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax1 = ParticipantPage(pax1_page)
        pax1.join("TopScorer")
        pax1.submit_question("Question one?")
        pax1.submit_question("Question two?")

        # P2 joins and submits 1 question
        pax2_ctx = browser.new_context()
        pax2_page = pax2_ctx.new_page()
        pax2_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax2 = ParticipantPage(pax2_page)
        pax2.join("RunnerUp")
        pax2.submit_question("Question three?")

        # Wait for scores to be assigned
        _await_condition(
            lambda: pax1.get_score() > 0,
            timeout_ms=5000, msg="P1 didn't get score from Q&A"
        )

        # Trigger leaderboard show (daemon endpoint)
        _api_call("POST", f"/api/{session_id}/leaderboard/show", base=DAEMON_BASE)

        # Both participants should see the leaderboard overlay
        _await_condition(
            lambda: pax1_page.evaluate(
                "() => getComputedStyle(document.getElementById('leaderboard-overlay')).display"
            ) == "flex",
            timeout_ms=5000, msg="P1 didn't see leaderboard overlay"
        )
        _await_condition(
            lambda: pax2_page.evaluate(
                "() => getComputedStyle(document.getElementById('leaderboard-overlay')).display"
            ) == "flex",
            timeout_ms=5000, msg="P2 didn't see leaderboard overlay"
        )

        # P1 should see personal rank
        my_rank = pax1_page.locator("#leaderboard-my-rank")
        expect(my_rank).to_be_visible(timeout=3000)
        rank_text = my_rank.inner_text().strip()
        assert len(rank_text) > 0, "P1 should see rank text"

        print(f"P1 rank text: '{rank_text}'")
        print("SUCCESS: Leaderboard shows personal rank!")
        browser.close()


# ── 6. Escape closes all participant modals ───────────────────────────────

def test_escape_closes_all_participant_modals():
    """Open overlays programmatically, press Escape, all should close."""
    session_id = _create_session("EscapeClose")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("EscapeTester")

        # Open overlays programmatically
        pax_page.evaluate("""() => {
            const ids = ['notes-overlay', 'summary-overlay', 'slides-overlay'];
            ids.forEach(id => {
                const el = document.getElementById(id);
                if (el) el.classList.add('open');
            });
        }""")

        # Verify at least one overlay is open
        _await_condition(
            lambda: pax_page.evaluate("""() => {
                const ids = ['notes-overlay', 'summary-overlay', 'slides-overlay'];
                return ids.some(id => {
                    const el = document.getElementById(id);
                    return el && el.classList.contains('open');
                });
            }"""),
            timeout_ms=3000, msg="No overlay was opened"
        )

        # Press Escape
        pax_page.keyboard.press("Escape")
        pax_page.wait_for_timeout(500)

        # All overlays should be closed
        all_closed = pax_page.evaluate("""() => {
            const ids = ['notes-overlay', 'summary-overlay', 'slides-overlay'];
            return ids.every(id => {
                const el = document.getElementById(id);
                return !el || !el.classList.contains('open');
            });
        }""")
        assert all_closed, "Not all overlays closed after Escape"

        # Avatar modal should also be gone
        avatar_gone = pax_page.evaluate("""() => {
            const el = document.getElementById('avatar-modal');
            return !el;
        }""")
        assert avatar_gone, "Avatar modal should be closed after Escape"

        print("SUCCESS: Escape closes all participant modals!")
        browser.close()


# ── 7. Host tab survives reload ───────────────────────────────────────────

def test_host_tab_survives_reload():
    """Switch to Q&A tab, reload page, Q&A tab should still be active."""
    session_id = _create_session("TabReload")
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


# ── 8. QR code rendered ──────────────────────────────────────────────────

def test_qr_code_rendered():
    """Host page should render a QR code."""
    session_id = _create_session("QRCode")
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


# ── 9. Participant link displayed ─────────────────────────────────────────

def test_participant_link_displayed():
    """Host page should show a participant link."""
    session_id = _create_session("PaxLink")
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


# ── 10. Poll download captures two polls ──────────────────────────────────

def test_poll_download_captures_two_polls():
    """Create 2 polls sequentially, verify download text contains both questions with correct marks."""
    session_id = _create_session("TwoPolls")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_page)
        expect(host_page.locator("#ws-badge.connected")).to_be_visible(timeout=10000)

        # Also need a participant to vote (so polls get saved to history)
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("PollVoter")

        _await_condition(
            lambda: "PollVoter" in host_page.inner_text("body"),
            timeout_ms=5000, msg="Host didn't see PollVoter"
        )

        # ── Poll 1 ──
        host.create_poll("What is 2+2?", ["3", "4", "5"])
        expect(pax_page.locator(".option-btn").first).to_be_visible(timeout=5000)
        pax.vote_for("4")
        host.close_poll()
        host.mark_correct("4")
        # Remove poll
        host_page.wait_for_timeout(500)
        _api_call("DELETE", f"/api/{session_id}/poll", base=DAEMON_BASE)
        host_page.wait_for_timeout(500)

        # ── Poll 2 ──
        host.create_poll("Capital of Italy?", ["Berlin", "Rome", "Madrid"])
        expect(pax_page.locator(".option-btn").first).to_be_visible(timeout=5000)
        pax.vote_for("Rome")
        host.close_poll()
        host.mark_correct("Rome")
        host_page.wait_for_timeout(500)

        # Verify download text contains both polls
        download_text = host.get_download_text()
        assert "2+2" in download_text, f"Poll 1 question not found in download text: {download_text}"
        assert "Capital of Italy" in download_text, f"Poll 2 question not found in download text: {download_text}"
        assert "✅" in download_text, f"No correct mark (✅) found in download text: {download_text}"

        print(f"Download text:\n{download_text}")
        print("SUCCESS: Poll download captures two polls!")
        browser.close()
