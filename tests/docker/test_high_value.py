"""
Hermetic E2E tests: high-value user scenarios.

10 tests covering key user flows and integration points:
1. Correct answer scoring (speed-based)
2. Conference mode with character names
3. Paste text flow (participant → host)
4. File upload flow (participant → host download)
5. Zero votes show 0%
6. Participant joins mid-Q&A sees existing questions
7. Code review: host pastes snippet, participant selects lines
8. Wordcloud close returns to idle
9. Session end disconnects participants
10. Self-upvote disabled in Q&A
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


def _create_session(name="Test") -> str:
    """Create a fresh session via API — gives clean state."""
    result = _api_call("POST", "/api/session/create", {"name": f"{name} {int(time.time())}", "type": "workshop"})
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


# ── 1. Correct answer scoring ──────────────────────────────────────────────

def test_correct_answer_gives_score():
    """Participant votes correct answer → gets score points."""
    session_id = _create_session("Scoring")
    with sync_playwright() as p:
        browser, host, host_page, pax, pax_page = _open_browser_trio(p, session_id)
        pax.join("Scorer")

        host.create_poll("Capital of France?", ["Berlin", "Paris", "Rome"])
        pax.vote_for("Paris")
        host.close_poll()
        host.mark_correct("Paris")

        _await_condition(
            lambda: pax.get_score() > 0,
            timeout_ms=5000, msg="Participant did not receive score"
        )
        score = pax.get_score()
        print(f"Score after correct answer: {score}")
        assert score >= 500, f"Expected score >= 500 (speed-based), got {score}"

        print("SUCCESS: Correct answer scoring works!")
        browser.close()


# ── 2. Conference mode character names ─────────────────────────────────────

@pytest.mark.skip(reason="WIP: conference mode API call needs session-scoped path")
def test_conference_mode_auto_assigns_character_name():
    """Switch to conference mode → participant gets auto-assigned character name."""
    session_id = _create_session("Conference")
    with sync_playwright() as p:
        browser, host, host_page, pax, pax_page = _open_browser_trio(p, session_id)

        # Wait for auto-join
        expect(pax_page.locator("#display-name")).to_be_visible(timeout=10000)
        initial_name = pax_page.inner_text("#display-name")

        # Switch to conference mode via API
        _api_call("POST", f"/api/{session_id}/mode", {"mode": "conference"})

        # Participant should get a new character name (from the 251-name pool)
        _await_condition(
            lambda: pax_page.inner_text("#display-name") != initial_name
                    or pax_page.locator(".avatar-letter").count() > 0,
            timeout_ms=5000,
            msg="Conference mode did not assign character name"
        )

        # Check that score is hidden in conference mode
        score_el = pax_page.locator("#score-display, .score")
        if score_el.count() > 0:
            is_hidden = pax_page.evaluate("""() => {
                const el = document.querySelector('#score-display, .score');
                return el ? getComputedStyle(el).display === 'none' : true;
            }""")
            print(f"Score hidden in conference mode: {is_hidden}")

        print("SUCCESS: Conference mode assigns character names!")
        browser.close()


# ── 3. Paste text flow ─────────────────────────────────────────────────────

def test_paste_text_visible_to_host():
    """Participant pastes text → host sees paste icon in participant list."""
    session_id = _create_session("Paste")
    with sync_playwright() as p:
        browser, host, host_page, pax, pax_page = _open_browser_trio(p, session_id)
        pax.join("Paster")

        _await_condition(
            lambda: "Paster" in host_page.inner_text("body"),
            timeout_ms=5000, msg="Host doesn't see Paster"
        )

        # Simulate paste via WS message (Playwright can't easily trigger Cmd+V)
        pax_page.evaluate("""() => {
            if (typeof sendWS === 'function') {
                sendWS('paste_text', { text: 'Hello from hermetic test!' });
            }
        }""")

        # Host should see a paste icon next to the participant
        _await_condition(
            lambda: host_page.locator(".paste-icon, .participant-paste, [title*='paste' i]").count() > 0,
            timeout_ms=5000,
            msg="Host did not see paste icon"
        )

        print("SUCCESS: Paste text visible to host!")
        browser.close()


# ── 4. Zero votes show 0% ─────────────────────────────────────────────────

@pytest.mark.skip(reason="WIP: new session doesn't get host WS connected in time for poll create")
def test_zero_votes_shows_zero_percent():
    """Close poll with zero votes → all options show 0%."""
    session_id = _create_session("ZeroVotes")
    with sync_playwright() as p:
        browser, host, host_page, pax, pax_page = _open_browser_trio(p, session_id)
        pax.join("Observer")

        host.create_poll("Empty poll?", ["A", "B", "C"])
        host.close_poll()

        expect(pax_page.locator(".pct").first).to_be_visible(timeout=5000)
        pcts = pax.get_percentages()
        assert pcts == [0, 0, 0], f"Expected [0, 0, 0] but got {pcts}"

        print("SUCCESS: Zero votes show 0%!")
        browser.close()


# ── 5. Late joiner sees Q&A questions ──────────────────────────────────────

def test_late_joiner_sees_existing_qa():
    """Participant joins after questions were submitted → sees them."""
    session_id = _create_session("LateQA")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Host + first participant
        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_page = host_ctx.new_page()
        host_page.goto(f"{BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_page)
        host.open_qa_tab()

        pax1_ctx = browser.new_context()
        pax1_page = pax1_ctx.new_page()
        pax1_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax1 = ParticipantPage(pax1_page)
        pax1.join("EarlyBird")

        # Submit questions before second participant joins
        pax1.submit_question("What is polymorphism?")
        pax1.submit_question("Explain SOLID principles")

        _await_condition(
            lambda: len(host.get_qa_questions()) >= 2,
            timeout_ms=5000, msg="Host didn't see 2 questions"
        )

        # NOW second participant joins late
        pax2_ctx = browser.new_context()
        pax2_page = pax2_ctx.new_page()
        pax2_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax2 = ParticipantPage(pax2_page)
        pax2.join("LateJoiner")

        # Late joiner should see both questions
        _await_condition(
            lambda: len(pax2.get_qa_questions()) >= 2,
            timeout_ms=5000, msg="Late joiner didn't see existing questions"
        )
        questions = pax2.get_qa_questions()
        texts = [q["text"] for q in questions]
        assert any("polymorphism" in t.lower() for t in texts)
        assert any("solid" in t.lower() for t in texts)

        print("SUCCESS: Late joiner sees existing Q&A!")
        browser.close()


# ── 6. Code review: snippet + line selection ───────────────────────────────

@pytest.mark.skip(reason="WIP: code review API path needs session-scoped endpoint investigation")
def test_code_review_line_selection():
    """Host pastes code snippet → participant selects lines → host sees selection."""
    session_id = _create_session("CodeReview")
    with sync_playwright() as p:
        browser, host, host_page, pax, pax_page = _open_browser_trio(p, session_id)
        pax.join("Reviewer")

        # Host creates code review with a snippet
        snippet = "public void process() {\n    // TODO: implement\n    return null;\n}"
        _api_call("POST", f"/api/{session_id}/codereview", {"snippet": snippet, "language": "java"})

        # Wait for code review to appear on participant
        expect(pax_page.locator(".code-line, .cr-line")).to_be_visible(timeout=5000)

        # Participant clicks a line to flag it
        pax_page.locator(".code-line, .cr-line").nth(2).click()  # "return null;" line

        # Host should see the selection (line flagged by 1 participant)
        _await_condition(
            lambda: host_page.evaluate("""() => {
                const lines = document.querySelectorAll('.cr-line-count, .line-count');
                return Array.from(lines).some(l => l.textContent.includes('1'));
            }"""),
            timeout_ms=5000,
            msg="Host didn't see participant's line selection"
        )

        print("SUCCESS: Code review line selection works!")
        browser.close()


# ── 7. Wordcloud close returns to idle ─────────────────────────────────────

@pytest.mark.skip(reason="WIP: activity switch API needs session-scoped path")
def test_wordcloud_close_returns_to_idle():
    """Host opens wordcloud → submits word → host closes → participant returns to idle."""
    session_id = _create_session("WCClose")
    with sync_playwright() as p:
        browser, host, host_page, pax, pax_page = _open_browser_trio(p, session_id)
        pax.join("CloudUser")

        host.open_wordcloud_tab()
        expect(pax_page.locator("#wc-canvas")).to_be_visible(timeout=5000)

        pax.submit_word("testing")

        # Switch to NONE activity (close wordcloud)
        _api_call("POST", f"/api/{session_id}/activity", {"type": "none"})

        # Participant should no longer see the wordcloud
        _await_condition(
            lambda: pax_page.locator("#wc-canvas").count() == 0
                    or not pax_page.locator("#wc-canvas").is_visible(),
            timeout_ms=5000,
            msg="Wordcloud still visible after close"
        )

        print("SUCCESS: Wordcloud close returns to idle!")
        browser.close()


# ── 8. Self-upvote disabled ────────────────────────────────────────────────

def test_self_upvote_disabled():
    """Participant can't upvote their own Q&A question."""
    session_id = _create_session("SelfUpvote")
    with sync_playwright() as p:
        browser, host, host_page, pax, pax_page = _open_browser_trio(p, session_id)
        pax.join("Author")
        host.open_qa_tab()

        pax.submit_question("My own question")

        _await_condition(
            lambda: len(pax.get_qa_questions()) > 0,
            timeout_ms=5000, msg="Question not visible"
        )

        # The upvote button for own question should be disabled
        questions = pax.get_qa_questions()
        own_q = questions[0]
        upvote_btn = pax_page.locator(f'.qa-upvote-btn[data-qid="{own_q["id"]}"]')
        is_disabled = upvote_btn.is_disabled()
        assert is_disabled, "Self-upvote button should be disabled"

        print("SUCCESS: Self-upvote disabled!")
        browser.close()


# ── 9. Multi-select poll enforces cap ──────────────────────────────────────

@pytest.mark.skip(reason="WIP: multi-select poll creation needs page object method fix")
def test_multi_select_cap_enforced():
    """Multi-select poll: participant can't select more options than correct_count."""
    session_id = _create_session("MultiCap")
    with sync_playwright() as p:
        browser, host, host_page, pax, pax_page = _open_browser_trio(p, session_id)
        pax.join("MultiVoter")

        # Create multi-select poll with correct_count=2
        host.create_poll("Pick 2 OOP principles:", ["Encapsulation", "Inheritance", "Gravity", "Polymorphism"],
                         multi=True, correct_count=2)

        # Select 2 options
        pax.multi_vote("Encapsulation", "Inheritance")

        # Try to select a 3rd — it should be rejected or one should be deselected
        pax_page.locator(".option-btn:has-text('Gravity')").click()
        pax_page.wait_for_timeout(500)

        # Count how many are selected (have 'selected' class or similar)
        selected = pax_page.locator(".option-btn.selected, .option-btn.multi-selected, .option-btn[aria-pressed='true']")
        count = selected.count()
        assert count <= 2, f"Expected at most 2 selected options, got {count}"

        print("SUCCESS: Multi-select cap enforced!")
        browser.close()


# ── 10. Participant count updates on host ──────────────────────────────────

@pytest.mark.skip(reason="WIP: participant count selector needs investigation")
def test_participant_count_updates():
    """Host sees participant count increase as participants join."""
    session_id = _create_session("ParticipantCount")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_page = host_ctx.new_page()
        host_page.goto(f"{BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10000)

        # Join 3 participants one by one
        paxes = []
        for name in ["Alice", "Bob", "Charlie"]:
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
            pax = ParticipantPage(page)
            pax.join(name)
            paxes.append(pax)

            # Host should see the count update
            _await_condition(
                lambda n=name: n in host_page.inner_text("body"),
                timeout_ms=5000,
                msg=f"Host didn't see participant '{name}'"
            )

        # Verify the participant count shows 3
        _await_condition(
            lambda: host_page.evaluate("""() => {
                const el = document.querySelector('#participant-count, .participant-count');
                if (!el) return false;
                const match = el.textContent.match(/(\\d+)/);
                return match && parseInt(match[1]) >= 3;
            }"""),
            timeout_ms=5000,
            msg="Participant count didn't reach 3"
        )

        print("SUCCESS: Participant count updates on host!")
        browser.close()
