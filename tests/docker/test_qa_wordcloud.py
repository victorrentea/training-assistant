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
