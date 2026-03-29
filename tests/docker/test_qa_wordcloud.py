"""
Hermetic E2E tests: Q&A and Word Cloud flows.

- Q&A: participant submits question → host sees it, host edits → participant sees update
- Word cloud: host opens → participant submits word → appears in "my words"
"""

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


def _clear_qa(session_id: str) -> None:
    """Clear all Q&A questions via API."""
    import base64
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    req = urllib.request.Request(
        f"{BASE}/api/{session_id}/qa/clear",
        method="POST",
        headers={"Authorization": f"Basic {auth}", "Content-Length": "0"},
        data=b""
    )
    urllib.request.urlopen(req, timeout=5)


def _get_or_create_session() -> str:
    try:
        with urllib.request.urlopen(f"{BASE}/api/session/active", timeout=5) as resp:
            data = json.loads(resp.read())
            if data.get("session_id"):
                return data["session_id"]
    except Exception:
        pass
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        page = ctx.new_page()
        page.goto(f"{BASE}/host", wait_until="networkidle")
        if re.search(r"/host/[a-zA-Z0-9]+", page.url):
            sid = page.url.split("/host/")[-1].split("?")[0]
            browser.close()
            return sid
        page.locator("#session-name-input").fill("QA WC Tests")
        btn = page.locator("#create-btn-workshop")
        expect(btn).to_be_enabled(timeout=3000)
        btn.click()
        page.wait_for_url(re.compile(r"/host/[a-zA-Z0-9]+"), timeout=15000)
        sid = page.url.split("/host/")[-1].split("?")[0]
        browser.close()
        return sid


# ── Q&A Tests ───────────────────────────────────────────────────────────────


def test_qa_submit_and_host_sees():
    """Participant submits a question → host sees it in Q&A panel."""
    session_id = _get_or_create_session()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_page)

        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("Questioner")

        # Host switches to Q&A tab
        host.open_qa_tab()

        # Participant submits a question
        pax.submit_question("What is dependency injection?")
        print("Question submitted")

        # Host should see the question
        _await_condition(
            lambda: len(host.get_qa_questions()) > 0,
            timeout_ms=5000,
            msg="Host did not see the question"
        )
        questions = host.get_qa_questions()
        assert len(questions) >= 1
        assert "dependency injection" in questions[0]["text"].lower()
        assert questions[0]["upvotes"] == 0
        assert questions[0]["answered"] is False
        print(f"Host sees question: '{questions[0]['text']}'")

        print("SUCCESS: Q&A submission visible to host!")
        browser.close()


def test_qa_host_edits_participant_sees():
    """Host edits a question → participant sees the updated text."""
    session_id = _get_or_create_session()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_page)

        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("Editor")

        host.open_qa_tab()
        pax.submit_question("What is SOLID?")

        _await_condition(
            lambda: len(host.get_qa_questions()) > 0,
            timeout_ms=5000,
            msg="Host did not see the question"
        )

        q_id = host.get_qa_questions()[0]["id"]
        host.edit_question(q_id, "What are the SOLID principles in OOP?")
        print(f"Host edited question {q_id}")

        # Participant should see the edited text
        _await_condition(
            lambda: any("SOLID principles" in q["text"] for q in pax.get_qa_questions()),
            timeout_ms=5000,
            msg="Participant did not see the edited question"
        )
        print("Participant sees edited question")

        print("SUCCESS: Q&A edit visible to participant!")
        browser.close()


def test_qa_host_deletes_question():
    """Host deletes question → both host and participant lists are empty."""
    session_id = _get_or_create_session()
    _clear_qa(session_id)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_page)

        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("Carmen")

        host.open_qa_tab()
        pax.submit_question("This will be deleted")

        _await_condition(
            lambda: len(host.get_qa_questions()) > 0,
            timeout_ms=5000, msg="Host did not see question"
        )
        q_id = host.get_qa_questions()[0]["id"]
        host.delete_question(q_id)

        expect(host_page.locator(".qa-card")).to_have_count(0, timeout=3000)
        pax.expect_question_count(0)
        print("SUCCESS: Q&A delete works!")
        browser.close()


def test_qa_host_marks_answered():
    """Host marks question answered → participant sees answered styling."""
    session_id = _get_or_create_session()
    _clear_qa(session_id)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10000)
        host = HostPage(host_page)

        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("Diana")

        host.open_qa_tab()
        pax.submit_question("Can Spring Boot run on GraalVM?")

        _await_condition(
            lambda: len(host.get_qa_questions()) > 0,
            timeout_ms=5000, msg="Host did not see question"
        )
        q_id = host.get_qa_questions()[0]["id"]
        print(f"Toggling answered on question: {q_id}")
        host.toggle_answered(q_id)

        # Host card gets qa-answered class
        expect(host_page.locator(f'.qa-card[data-id="{q_id}"]')).to_have_class(
            re.compile(r"qa-answered"), timeout=5000
        )
        # Participant card gets qa-answered-p class
        pax.expect_question_answered(q_id)
        print("SUCCESS: Q&A mark answered works!")
        browser.close()


def test_qa_upvoting_and_sort_order():
    """3 participants upvote questions → sorted by upvotes descending."""
    session_id = _get_or_create_session()
    _clear_qa(session_id)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_page)
        host.open_qa_tab()

        # 3 participants
        paxes = []
        for name in ["P1", "P2", "P3"]:
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
            pax = ParticipantPage(page)
            pax.join(name)
            paxes.append(pax)

        p1, p2, p3 = paxes

        # P1 submits 3 questions
        p1.submit_question("Q-Alpha")
        p1.submit_question("Q-Beta")
        p1.submit_question("Q-Gamma")

        _await_condition(
            lambda: len(host.get_qa_questions()) >= 3,
            timeout_ms=5000, msg="Host did not see 3 questions"
        )

        # Get question IDs from host (ordered by submission time initially)
        host_qs = host.get_qa_questions()
        q_alpha = next(q for q in host_qs if "Alpha" in q["text"])
        q_beta = next(q for q in host_qs if "Beta" in q["text"])

        # P2 upvotes Alpha and Beta, P3 upvotes only Alpha
        p2.upvote_question(q_alpha["id"])
        p2.upvote_question(q_beta["id"])
        p3.upvote_question(q_alpha["id"])

        # Wait for upvotes to propagate
        _await_condition(
            lambda: any(q["upvotes"] >= 2 for q in host.get_qa_questions()),
            timeout_ms=5000, msg="Upvotes did not propagate"
        )

        # Check final state: Alpha=2, Beta=1, Gamma=0
        final = host.get_qa_questions()
        alpha = next(q for q in final if "Alpha" in q["text"])
        beta = next(q for q in final if "Beta" in q["text"])
        gamma = next(q for q in final if "Gamma" in q["text"])
        assert alpha["upvotes"] == 2, f"Alpha expected 2 upvotes, got {alpha['upvotes']}"
        assert beta["upvotes"] == 1, f"Beta expected 1 upvote, got {beta['upvotes']}"
        assert gamma["upvotes"] == 0, f"Gamma expected 0 upvotes, got {gamma['upvotes']}"

        # Questions should be sorted by upvotes descending
        assert final[0]["upvotes"] >= final[1]["upvotes"] >= final[2]["upvotes"], \
            f"Questions not sorted by upvotes: {[q['upvotes'] for q in final]}"

        print(f"Upvotes: Alpha={alpha['upvotes']}, Beta={beta['upvotes']}, Gamma={gamma['upvotes']}")
        print("SUCCESS: Q&A upvoting and sort order works!")
        browser.close()


# ── Leaderboard Tests ──────────────────────────────────────────────────────


def test_leaderboard_show_and_hide():
    """Host shows leaderboard → participant sees overlay → host hides it."""
    session_id = _get_or_create_session()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_page)

        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("LeaderTest")

        # Give participant some score (submit a Q&A question = 100 pts)
        host.open_qa_tab()
        pax.submit_question("Score me up")
        _await_condition(
            lambda: pax.get_score() >= 100,
            timeout_ms=5000, msg="Participant did not get score"
        )

        # Show leaderboard via API (host panel uses this)
        import base64
        auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
        req = urllib.request.Request(
            f"{BASE}/api/{session_id}/leaderboard/show",
            method="POST",
            headers={"Authorization": f"Basic {auth}", "Content-Length": "0"},
            data=b""
        )
        urllib.request.urlopen(req, timeout=5)

        # Participant should see leaderboard overlay
        pax_page.wait_for_function(
            "() => document.getElementById('leaderboard-overlay')?.style.display === 'flex'",
            timeout=8000
        )
        print("Participant sees leaderboard overlay")

        # Hide leaderboard
        req2 = urllib.request.Request(
            f"{BASE}/api/{session_id}/leaderboard/hide",
            method="POST",
            headers={"Authorization": f"Basic {auth}", "Content-Length": "0"},
            data=b""
        )
        urllib.request.urlopen(req2, timeout=5)

        pax_page.wait_for_function(
            "() => document.getElementById('leaderboard-overlay')?.style.display === 'none'",
            timeout=8000
        )
        print("Leaderboard hidden")

        print("SUCCESS: Leaderboard show/hide works!")
        browser.close()


# ── Word Cloud Tests ────────────────────────────────────────────────────────


def test_wordcloud_submit_appears_in_my_words():
    """Host opens wordcloud → participant submits word → appears in 'my words'."""
    session_id = _get_or_create_session()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_page)

        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("CloudMaker")

        # Host opens wordcloud tab (switches activity to WORDCLOUD)
        host.open_wordcloud_tab()

        # Participant should see the word cloud canvas
        expect(pax_page.locator("#wc-canvas")).to_be_visible(timeout=5000)
        print("Participant sees word cloud canvas")

        # Participant submits a word
        pax.submit_word("microservices")
        print("Word submitted: microservices")

        # Should appear in participant's "my words" section
        expect(pax_page.locator("#wc-my-words .wc-my-word")).to_have_count(1, timeout=3000)
        expect(pax_page.locator("#wc-my-words .wc-my-word").first).to_contain_text("microservices")
        print("Word appears in 'my words'")

        print("SUCCESS: Word cloud submission works!")
        browser.close()
