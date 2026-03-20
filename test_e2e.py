"""
End-to-end browser tests using Playwright.

All interactions go through real browser UI via HostPage / ParticipantPage DSL.
Spins up a real uvicorn server on a free port, then drives Chromium (headless).

Run:
    pytest test_e2e.py -v
    pytest test_e2e.py -v --headed        # watch the browsers
"""

import os
import re
import subprocess
import sys
import time
import threading
from pathlib import Path

import requests
import pytest
from playwright.sync_api import Page, expect, sync_playwright

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage

PROD_URL = "https://interact.victorrentea.ro"
PROD_HOST_USER = os.environ.get("PROD_HOST_USERNAME", "host")
PROD_HOST_PASS = os.environ.get("PROD_HOST_PASSWORD", "host")

HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


# ---------------------------------------------------------------------------
# Server fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def server_url():
    """
    Spin up uvicorn on port 0 (OS picks a free port atomically).
    Parse the actual bound port from uvicorn's stderr output.
    """
    server_env = os.environ.copy()
    server_env["HOST_USERNAME"] = HOST_USER
    server_env["HOST_PASSWORD"] = HOST_PASS
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", "0"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env=server_env,
    )

    port = None
    deadline = time.time() + 15
    while time.time() < deadline:
        line = proc.stderr.readline().decode("utf-8", errors="replace")
        m = re.search(r"127\.0\.0\.1:(\d+)", line)
        if m:
            port = int(m.group(1))
            break
        if proc.poll() is not None:
            raise RuntimeError("uvicorn exited unexpectedly during startup")
    else:
        proc.terminate()
        raise RuntimeError("uvicorn did not log a bound port within 15s")

    threading.Thread(target=proc.stderr.read, daemon=True).start()

    yield f"http://127.0.0.1:{port}"

    proc.terminate()
    proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Browser / page fixtures
# ---------------------------------------------------------------------------

def _api(server_url, method, path, **kwargs):
    """Authenticated API call to a host-only endpoint."""
    return getattr(requests, method)(
        f"{server_url}{path}",
        auth=(HOST_USER, HOST_PASS),
        **kwargs,
    )


def _host_browser_ctx(server_url, playwright):
    browser = playwright.chromium.launch()
    ctx = browser.new_context(
        base_url=server_url,
        http_credentials={"username": HOST_USER, "password": HOST_PASS},
        viewport={"width": 1440, "height": 900},
    )
    return browser, ctx


def _pax_browser_ctx(server_url, playwright):
    browser = playwright.chromium.launch()
    ctx = browser.new_context(base_url=server_url)
    return browser, ctx


@pytest.fixture()
def host(server_url, playwright) -> HostPage:
    browser, ctx = _host_browser_ctx(server_url, playwright)
    page = ctx.new_page()
    page.goto("/host")
    yield HostPage(page)
    ctx.close()
    browser.close()


def _make_pax_fixture():
    @pytest.fixture()
    def pax(server_url, playwright) -> ParticipantPage:
        browser, ctx = _pax_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        page.goto("/")
        yield ParticipantPage(page)
        ctx.close()
        browser.close()
    return pax


pax  = _make_pax_fixture()
pax2 = _make_pax_fixture()
pax3 = _make_pax_fixture()


# ---------------------------------------------------------------------------
# TestPollLifecycle
# ---------------------------------------------------------------------------

class TestPollLifecycle:

    def test_participant_sees_poll_after_host_creates_it(self, host: HostPage, pax: ParticipantPage):
        pax.join("Alice")
        host.create_poll("Favourite language?", ["Python", "Java", "Go"])
        expect(pax._page.locator("#content h2")).to_have_text("Favourite language?", timeout=5000)
        expect(pax._page.locator(".option-btn")).to_have_count(3)

    def test_vote_registers_and_host_sees_count(self, host: HostPage, pax: ParticipantPage):
        pax.join("Bob")
        host.create_poll("Best DB?", ["Postgres", "MySQL", "SQLite"])
        pax.vote_for("Postgres")
        expect(host._page.locator("text=1 total vote")).to_be_visible(timeout=5000)

    def test_results_shown_after_poll_closed(self, host: HostPage, pax: ParticipantPage):
        pax.join("Carol")
        host.create_poll("Best cloud?", ["AWS", "GCP", "Azure"])
        pax.vote_for("AWS")
        host.close_poll()
        expect(pax._page.locator(".pct").first).to_be_visible(timeout=5000)
        expect(pax._page.locator(".closed-banner")).to_be_visible(timeout=5000)

    def test_zero_votes_shows_zero_percent(self, host: HostPage, pax: ParticipantPage):
        pax.join("Zara")
        host.create_poll("No votes poll?", ["A", "B", "C"])
        # Close poll without anyone voting
        host._page.click("text=Close voting")
        expect(host._page.locator("text=Open voting")).to_be_visible(timeout=5000)
        expect(pax._page.locator(".pct").first).to_be_visible(timeout=5000)
        pcts = pax.get_percentages()
        assert pcts == [0, 0, 0], f"Expected all 0% but got {pcts}"

    def test_correct_answer_feedback_shown_to_participant(self, host: HostPage, pax: ParticipantPage):
        pax.join("Dave")
        host.create_poll("Capital of France?", ["Berlin", "Paris", "Rome"])
        pax.vote_for_nth(1)  # Paris
        host.close_poll()
        host.mark_correct("Paris")
        expect(pax._page.locator(".result-icon", has_text="✅")).to_be_visible(timeout=5000)


# ---------------------------------------------------------------------------
# TestMultiSelect
# ---------------------------------------------------------------------------

class TestMultiSelect:

    def test_correct_count_hint_shown_to_participant(self, host: HostPage, pax: ParticipantPage):
        pax.join("Eve")
        host.create_poll("JVM languages?", ["Java", "Kotlin", "Python", "Scala"], multi=True)
        expect(pax._page.locator(".vote-msg").first).to_contain_text("exactly 2", timeout=5000)

    def test_participant_cannot_select_more_than_correct_count(self, host: HostPage, pax: ParticipantPage):
        pax.join("Frank")
        host.create_poll("Pick 2 fruits?", ["Apple", "Banana", "Cherry", "Date"], multi=True)
        pax._page.locator(".option-btn").nth(0).click()
        pax._page.locator(".option-btn").nth(1).click()
        expect(pax._page.locator(".option-btn").nth(2)).to_be_disabled(timeout=3000)
        expect(pax._page.locator(".option-btn").nth(3)).to_be_disabled(timeout=3000)


# ---------------------------------------------------------------------------
# TestRegressions
# ---------------------------------------------------------------------------

class TestRegressions:

    def test_autojoin_with_saved_name_no_js_error(self, server_url, playwright):
        browser = playwright.chromium.launch()
        ctx = browser.new_context(base_url=server_url)
        page = ctx.new_page()

        js_errors = []
        page.on("pageerror", lambda e: js_errors.append(str(e)))

        page.goto("/")
        page.evaluate("localStorage.setItem('workshop_participant_name', 'AutoJoiner')")
        page.evaluate("localStorage.setItem('workshop_participant_uuid', crypto.randomUUID())")
        page.reload()

        expect(page.locator("#main-screen")).to_be_visible(timeout=5000)
        assert js_errors == [], f"JS errors on auto-join: {js_errors}"

        ctx.close()
        browser.close()

    def test_participant_page_loads_with_zero_votes(self, host: HostPage, pax: ParticipantPage):
        """Regression: largestRemainder([0,0,...]) threw TypeError when poll had no votes."""
        js_errors = []
        pax._page.on("pageerror", lambda e: js_errors.append(str(e)))

        pax.join("Grace")
        host.create_poll("Zero votes test?", ["Yes", "No", "Maybe", "Skip"])

        expect(pax._page.locator("#content h2")).to_have_text("Zero votes test?", timeout=5000)
        assert js_errors == [], f"JS errors on participant page: {js_errors}"

    def test_generate_button_uses_only_transcript_or_topic_labels(self, host: HostPage):
        host.expect_generate_button_label("Generate from transcript ✨")
        host.set_quiz_topic("resilience")
        host.expect_generate_button_label("Generate on topic ✨")
        host.set_quiz_topic("")
        host.expect_generate_button_label("Generate from transcript ✨")

    def test_qa_input_and_button_heights_are_aligned_with_screenshots(self, host: HostPage, pax: ParticipantPage):
        pax.join("QaHeightUser")
        host.open_qa_tab()

        expect(host._page.locator("#host-qa-input")).to_be_visible(timeout=5000)
        expect(host._page.locator("#host-qa-submit-btn")).to_be_visible(timeout=5000)
        expect(pax._page.locator("#qa-input")).to_be_visible(timeout=5000)
        expect(pax._page.locator("#qa-submit-btn")).to_be_visible(timeout=5000)

        host_input_h = host._page.locator("#host-qa-input").bounding_box()["height"]
        host_btn_h = host._page.locator("#host-qa-submit-btn").bounding_box()["height"]
        pax_input_h = pax._page.locator("#qa-input").bounding_box()["height"]
        pax_btn_h = pax._page.locator("#qa-submit-btn").bounding_box()["height"]

        assert abs(host_input_h - host_btn_h) <= 1.0
        assert abs(pax_input_h - pax_btn_h) <= 1.0

        proof_dir = Path(__file__).parent / "docs" / "superpowers" / "specs"
        proof_dir.mkdir(parents=True, exist_ok=True)
        host._page.locator("#tab-content-qa").screenshot(path=str(proof_dir / "qa-height-host.png"))
        pax._page.locator(".qa-screen").screenshot(path=str(proof_dir / "qa-height-participant.png"))

    def test_version_tag_shows_elapsed_time_and_updates_under_day(self, host: HostPage, pax: ParticipantPage):
        # Host and participant should display relative elapsed labels by default.
        expect(host._page.locator("#version-tag")).to_contain_text(re.compile(r"(s|m|h) ago|from "))
        expect(pax._page.locator("#version-tag")).to_contain_text(re.compile(r"(s|m|h) ago|from "))

        # Force a fresh timestamp to verify live-update behavior under one day.
        host._page.evaluate(
            """
            () => {
              const d = new Date();
              const pad = n => String(n).padStart(2, '0');
              window.APP_VERSION = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
              window.renderDeployAge('version-tag');
            }
            """
        )
        pax._page.evaluate(
            """
            () => {
              const d = new Date();
              const pad = n => String(n).padStart(2, '0');
              window.APP_VERSION = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
              window.renderDeployAge('version-tag');
            }
            """
        )

        host_before = host._page.locator("#version-tag").inner_text().strip()
        pax_before = pax._page.locator("#version-tag").inner_text().strip()

        host._page.wait_for_timeout(1300)
        pax._page.wait_for_timeout(1300)

        host_after = host._page.locator("#version-tag").inner_text().strip()
        pax_after = pax._page.locator("#version-tag").inner_text().strip()

        assert host_before != host_after, f"Host version label did not live-update: {host_before}"
        assert pax_before != pax_after, f"Participant version label did not live-update: {pax_before}"

        proof_dir = Path(__file__).parent / "docs" / "superpowers" / "specs"
        proof_dir.mkdir(parents=True, exist_ok=True)
        host._page.screenshot(path=str(proof_dir / "version-age-host.png"), full_page=True)
        pax._page.screenshot(path=str(proof_dir / "version-age-participant.png"), full_page=True)

    def test_version_mismatch_shows_reload_prompt_and_stop_prevents_auto_reload(self, host: HostPage, pax: ParticipantPage):
        host._page.evaluate("window.APP_VERSION = '2000-01-01 00:00'; window.__versionReloadGuard && window.__versionReloadGuard.check('2099-01-01 00:00')")
        pax._page.evaluate("window.APP_VERSION = '2000-01-01 00:00'; window.__versionReloadGuard && window.__versionReloadGuard.check('2099-01-01 00:00')")

        expect(host._page.locator("#version-reload-banner")).to_be_visible(timeout=5000)
        expect(pax._page.locator("#version-reload-banner")).to_be_visible(timeout=5000)

        expect(host._page.locator("#version-reload-message")).to_contain_text("Reloading in")
        expect(pax._page.locator("#version-reload-message")).to_contain_text("Reloading in")

        host._page.click("#version-reload-stop")
        pax._page.click("#version-reload-stop")

        expect(host._page.locator("#version-reload-message")).to_contain_text("Auto-reload paused")
        expect(pax._page.locator("#version-reload-message")).to_contain_text("Auto-reload paused")

        proof_dir = Path(__file__).parent / "docs" / "superpowers" / "specs"
        proof_dir.mkdir(parents=True, exist_ok=True)
        host._page.screenshot(path=str(proof_dir / "version-mismatch-host.png"), full_page=True)
        pax._page.screenshot(path=str(proof_dir / "version-mismatch-participant.png"), full_page=True)


# ---------------------------------------------------------------------------
# TestWordCloud
# ---------------------------------------------------------------------------

class TestWordCloud:

    def test_host_opens_wordcloud_participant_sees_screen(self, host: HostPage, pax: ParticipantPage):
        pax.join("WcTester1")
        host.open_wordcloud_tab()
        expect(pax._page.locator("#wc-canvas")).to_be_visible(timeout=5000)

    def test_participant_submits_word_appears_in_my_words(self, host: HostPage, pax: ParticipantPage):
        pax.join("WcTester2")
        host.open_wordcloud_tab()
        expect(pax._page.locator("#wc-canvas")).to_be_visible(timeout=5000)

        pax.submit_word("microservices")

        expect(pax._page.locator("#wc-my-words .wc-my-word")).to_have_count(1, timeout=3000)
        expect(pax._page.locator("#wc-my-words .wc-my-word").first).to_have_text("microservices")

    def test_wordcloud_no_js_errors_on_submit(self, host: HostPage, pax: ParticipantPage):
        """Regression: _lastWordcloudTopic was never declared, causing ReferenceError in _drawCloud."""
        js_errors = []
        pax._page.on("pageerror", lambda e: js_errors.append(str(e)))

        pax.join("WcNoErr")
        host.open_wordcloud_tab()
        expect(pax._page.locator("#wc-canvas")).to_be_visible(timeout=5000)

        pax.submit_word("resilience")
        pax._page.wait_for_timeout(1000)
        assert js_errors == [], f"JS errors during word cloud: {js_errors}"

    def test_close_wordcloud_participant_returns_to_idle(self, host: HostPage, pax: ParticipantPage):
        pax.join("WcTester3")
        host.open_wordcloud_tab()
        expect(pax._page.locator("#wc-canvas")).to_be_visible(timeout=5000)

        # Host switches back to poll tab — deactivates word cloud
        host._page.click("text=Poll")
        expect(pax._page.locator("#wc-canvas")).not_to_be_visible(timeout=5000)


# ---------------------------------------------------------------------------
# TestQA
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def clean_qa(server_url):
    """Clear Q&A state before each test that uses it."""
    _api(server_url, "post", "/api/qa/clear")
    yield
    _api(server_url, "post", "/api/qa/clear")


@pytest.mark.usefixtures("clean_qa")
class TestQA:

    def test_participant_submits_question_host_sees_it(self, host: HostPage, pax: ParticipantPage):
        pax.join("Ana")
        host.open_qa_tab()
        pax.submit_question("What is the difference between JPA and JDBC?")
        questions = host.get_qa_questions()
        assert len(questions) == 1
        assert "JPA" in questions[0]["text"]
        assert questions[0]["upvotes"] == 0
        assert questions[0]["answered"] is False

    def test_host_edits_question_participant_sees_update(self, host: HostPage, pax: ParticipantPage):
        pax.join("Bruno")
        host.open_qa_tab()
        pax.submit_question("Orignial typo queston")
        q_id = host.get_qa_questions()[0]["id"]

        # Wait until participant sees the original question (confirms Q&A screen is active)
        pax.expect_question_text_visible("Orignial typo queston")

        host.edit_question(q_id, "Original question corrected")

        # Host sees updated text via WebSocket broadcast
        expect(host._page.locator(f'.qa-card[data-id="{q_id}"] .qa-text')).to_have_text(
            "Original question corrected", timeout=5000
        )
        # Participant sees updated text via WebSocket broadcast
        pax.expect_question_text_visible("Original question corrected")

    def test_host_deletes_question_participant_list_empty(self, host: HostPage, pax: ParticipantPage):
        pax.join("Carmen")
        host.open_qa_tab()
        pax.submit_question("This will be deleted")
        q_id = host.get_qa_questions()[0]["id"]

        host.delete_question(q_id)

        expect(host._page.locator(".qa-card")).to_have_count(0, timeout=3000)
        pax.expect_question_count(0)

    def test_host_marks_question_answered_participant_sees_it(self, host: HostPage, pax: ParticipantPage):
        pax.join("Diana")
        host.open_qa_tab()
        pax.submit_question("Can Spring Boot run on GraalVM?")
        q_id = host.get_qa_questions()[0]["id"]

        host.toggle_answered(q_id)

        # Host card gets qa-answered class
        expect(host._page.locator(f'.qa-card[data-id="{q_id}"]')).to_have_class(
            re.compile(r"qa-answered"), timeout=4000
        )
        # Participant card gets qa-answered-p class
        expect(pax._page.locator(f'.qa-card-p[data-id="{q_id}"]')).to_have_class(
            re.compile(r"qa-answered-p"), timeout=4000
        )

    def test_host_qa_action_labels_icons_and_edit_with_quotes(self, host: HostPage, pax: ParticipantPage):
        pax.join("Elena")
        host.open_qa_tab()
        pax.submit_question('Could "quoted" text break edit?')
        q_id = host.get_qa_questions()[0]["id"]

        first_card = host._page.locator(".qa-card").first
        expect(first_card.locator(".qa-actions button").nth(0)).to_contain_text("Answered")
        expect(first_card.locator(".qa-actions button").nth(2)).to_have_text("🗑")
        expect(host._page.locator("#clear-qa-btn")).to_have_text("🗑 Delete all")

        host.edit_question(q_id, "Edit works with quotes: \"alpha\" and apostrophe's")
        expect(host._page.locator(f'.qa-card[data-id="{q_id}"] .qa-text')).to_have_text(
            "Edit works with quotes: \"alpha\" and apostrophe's", timeout=5000
        )

        proof_dir = Path(__file__).parent / "docs" / "superpowers" / "specs"
        proof_dir.mkdir(parents=True, exist_ok=True)
        host._page.locator("#tab-content-qa").screenshot(path=str(proof_dir / "qa-host-actions.png"))

    def test_upvoting_and_sorted_order(self, server_url, playwright):
        """
        3 participants: P1 submits 3 questions, P2 upvotes 1, P3 upvotes 2.
        Expected upvote counts: Q1=2, Q2=1, Q3=0.
        Both host and participant lists must be sorted desc by upvotes.
        """
        b_host, ctx_host = _host_browser_ctx(server_url, playwright)
        b1, ctx1 = _pax_browser_ctx(server_url, playwright)
        b2, ctx2 = _pax_browser_ctx(server_url, playwright)
        b3, ctx3 = _pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1   = ParticipantPage(ctx1.new_page())
        p2   = ParticipantPage(ctx2.new_page())
        p3   = ParticipantPage(ctx3.new_page())

        host._page.goto("/host")
        p1._page.goto("/")
        p2._page.goto("/")
        p3._page.goto("/")

        p1.join("Alice")
        p2.join("Bob")
        p3.join("Carol")
        host.open_qa_tab()

        p1.submit_question("Question A")
        p1.submit_question("Question B")
        p1.submit_question("Question C")

        # Wait until all 3 questions are visible to p2 and p3
        p2.expect_question_count(3)
        p3.expect_question_count(3)

        # Identify question IDs from P2's perspective
        q2_questions = p2.get_qa_questions()
        # Questions appear in submission order initially; find by text
        id_a = next(q["id"] for q in q2_questions if q["text"] == "Question A")
        id_b = next(q["id"] for q in q2_questions if q["text"] == "Question B")

        # P2 upvotes Question A only
        p2.upvote_question(id_a)

        # P3 upvotes Question A and Question B
        p3.upvote_question(id_a)
        p3.upvote_question(id_b)

        # Wait for counts to propagate: Question A should show 2 upvotes
        expect(p1._page.locator(f'.qa-card-p[data-id="{id_a}"] .qa-upvote-btn')).to_contain_text(
            "2", timeout=5000
        )

        # Verify upvote counts from P1's view
        p1_questions = p1.get_qa_questions()
        by_id = {q["id"]: q for q in p1_questions}
        assert by_id[id_a]["upvotes"] == 2, f"Question A: expected 2 upvotes, got {by_id[id_a]['upvotes']}"
        assert by_id[id_b]["upvotes"] == 1, f"Question B: expected 1 upvote, got {by_id[id_b]['upvotes']}"
        id_c = next(q["id"] for q in p1_questions if q["text"] == "Question C")
        assert by_id[id_c]["upvotes"] == 0, f"Question C: expected 0 upvotes, got {by_id[id_c]['upvotes']}"

        # Verify sorted order on participant: A (2) > B (1) > C (0)
        p1_texts = p1.get_question_texts()
        assert p1_texts == ["Question A", "Question B", "Question C"], \
            f"Participant sort order wrong: {p1_texts}"

        # Verify sorted order on host
        host_questions = host.get_qa_questions()
        host_texts = [q["text"] for q in host_questions]
        assert host_texts == ["Question A", "Question B", "Question C"], \
            f"Host sort order wrong: {host_texts}"

        for ctx in (ctx_host, ctx1, ctx2, ctx3):
            ctx.close()
        for b in (b_host, b1, b2, b3):
            b.close()

    def test_own_question_upvote_button_disabled(self, host: HostPage, pax: ParticipantPage):
        pax.join("Frank")
        host.open_qa_tab()
        pax.submit_question("My own question")
        expect(pax._page.locator(".qa-upvote-btn").first).to_be_disabled(timeout=3000)

    def test_already_upvoted_button_becomes_disabled(self, server_url, playwright):
        b_host, ctx_host = _host_browser_ctx(server_url, playwright)
        b1, ctx1 = _pax_browser_ctx(server_url, playwright)
        b2, ctx2 = _pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1   = ParticipantPage(ctx1.new_page())
        p2   = ParticipantPage(ctx2.new_page())

        host._page.goto("/host")
        p1._page.goto("/")
        p2._page.goto("/")

        p1.join("Greta")
        p2.join("Henry")
        host.open_qa_tab()

        p1.submit_question("Question to upvote once")
        p2.expect_question_count(1)
        q_id = p2.get_qa_questions()[0]["id"]

        p2.upvote_question(q_id)

        btn = p2._page.locator(f'.qa-upvote-btn[data-qid="{q_id}"]')
        expect(btn).to_be_disabled(timeout=3000)
        expect(btn).to_have_class(re.compile(r"qa-upvoted"))

        for ctx in (ctx_host, ctx1, ctx2):
            ctx.close()
        for b in (b_host, b1, b2):
            b.close()


# ---------------------------------------------------------------------------
# TestTabPersistence
# ---------------------------------------------------------------------------

class TestTabPersistence:

    def test_host_tab_survives_reload(self, server_url, playwright):
        """Switching to Q&A tab, reloading the page, should keep Q&A active."""
        b, ctx = _host_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        page.goto("/host")

        host = HostPage(page)
        host.open_qa_tab()

        # Verify Q&A tab is active before reload
        expect(page.locator("#tab-qa.active")).to_be_visible(timeout=3000)
        expect(page.locator("#tab-content-qa")).to_be_visible()

        # Reload the page
        page.reload()

        # After reload, Q&A tab should still be active
        expect(page.locator("#tab-qa.active")).to_be_visible(timeout=5000)
        expect(page.locator("#tab-content-qa")).to_be_visible(timeout=5000)
        expect(page.locator("#tab-content-poll")).to_be_hidden()

        ctx.close()
        b.close()


# ---------------------------------------------------------------------------
# TestPollDownload
# ---------------------------------------------------------------------------

class TestPollDownload:

    def test_download_captures_two_polls_with_correct_answers(self, host: HostPage, pax: ParticipantPage):
        """
        Create 2 polls, vote, close, mark correct answers.
        Verify the download text includes both questions with ✅ on correct options.
        """
        pax.join("Zara")

        # Ensure poll tab is active (previous tests may have switched to Q&A)
        host._page.click("text=Poll")

        # --- Poll 1: single-select ---
        host.create_poll("What is 2+2?", ["Three", "Four", "Five"])
        expect(pax._page.locator(".option-btn")).to_have_count(3, timeout=5000)
        pax.vote_for("Four")
        host.close_poll()
        host.mark_correct("Four")

        # Wait for poll history to be recorded in localStorage
        host._page.wait_for_timeout(500)
        history = host.get_poll_history()
        assert len(history) >= 1, f"Expected at least 1 poll in history, got {len(history)}"

        # Remove poll to make room for the next one
        host._page.click("text=Remove question")
        host._page.wait_for_timeout(500)

        # --- Poll 2: single-select ---
        host.create_poll("Capital of France?", ["Berlin", "Paris", "Rome", "Madrid"])
        expect(pax._page.locator(".option-btn")).to_have_count(4, timeout=5000)
        pax.vote_for("Paris")
        host.close_poll()
        host.mark_correct("Paris")

        host._page.wait_for_timeout(500)
        history = host.get_poll_history()
        assert len(history) >= 2, f"Expected at least 2 polls in history, got {len(history)}"

        # Verify download text content
        text = host.get_download_text()
        assert "What is 2+2?" in text
        assert "Capital of France?" in text

        # Check correct answers are marked with ✅
        lines = text.split("\n")
        # Poll 1: option B (Four) should have ✅
        b_line_poll1 = [l for l in lines if l.strip().startswith("B.") and "Four" in l]
        assert any("✅" in l for l in b_line_poll1), f"Option 'Four' should be marked correct: {b_line_poll1}"
        # Poll 1: options A (Three), C (Five) should NOT have ✅
        a_line_poll1 = [l for l in lines if l.strip().startswith("A.") and "Three" in l]
        assert all("✅" not in l for l in a_line_poll1), f"Option 'Three' should not be marked correct"

        # Poll 2: option B (Paris) should have ✅
        b_line_poll2 = [l for l in lines if l.strip().startswith("B.") and "Paris" in l]
        assert any("✅" in l for l in b_line_poll2), f"Option 'Paris' should be marked correct: {b_line_poll2}"
        # Poll 2: options A, C, D should NOT have ✅
        non_correct = [l for l in lines if any(c in l for c in ["Berlin", "Rome", "Madrid"]) and l.strip().startswith(("A.", "C.", "D."))]
        assert all("✅" not in l for l in non_correct), f"Non-correct options should not be marked: {non_correct}"


# ---------------------------------------------------------------------------
# Production smoke tests
# ---------------------------------------------------------------------------

@pytest.mark.prod
def _prod_request(method, path, retries=3, **kwargs):
    """Make a request to PROD_URL with retries for transient DNS/network errors."""
    kwargs.setdefault("timeout", 10)
    for attempt in range(retries):
        try:
            return requests.request(method, f"{PROD_URL}{path}", **kwargs)
        except requests.exceptions.ConnectionError:
            if attempt == retries - 1:
                raise
            time.sleep(2)


class TestProductionSmoke:
    """
    Smoke tests against the live Railway deployment.
    Run with: pytest test_e2e.py -m prod -v
    Requires HOST_USERNAME / HOST_PASSWORD env vars.
    """

    def test_prod_participant_page_accessible(self):
        resp = _prod_request("GET", "/")
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "")

    def test_prod_host_page_requires_auth(self):
        resp = _prod_request("GET", "/host")
        assert resp.status_code == 401

    @pytest.mark.skipif(
        not os.environ.get("PROD_HOST_PASSWORD"),
        reason="PROD_HOST_PASSWORD not set"
    )
    def test_prod_host_page_accessible_with_credentials(self):
        resp = _prod_request("GET", "/host", auth=(PROD_HOST_USER, PROD_HOST_PASS))
        assert resp.status_code == 200

    def test_prod_api_status_public(self):
        resp = _prod_request("GET", "/api/status")
        assert resp.status_code == 200
        assert "participants" in resp.json()

    def test_prod_api_poll_requires_auth(self):
        resp = _prod_request("POST", "/api/poll", json={})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# TestNotifications
# ---------------------------------------------------------------------------

class TestNotifications:
    """Browser notification button behaviour."""

    def test_notif_btn_hidden_on_load(self, server_url, playwright):
        """The 🔔 button is hidden before any join."""
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(server_url)
        expect(page.locator("#notif-btn")).to_be_hidden()
        browser.close()

    def test_notif_btn_hidden_after_fresh_join(self, server_url, playwright):
        """After a fresh join (user gesture), no 🔔 button shown —
        permission was requested inline via the join gesture, so
        Notification.permission is already 'granted' when ws.onopen runs."""
        browser = playwright.chromium.launch()
        # Grant notifications so requestPermission() resolves immediately
        ctx = browser.new_context(permissions=["notifications"])
        page = ctx.new_page()
        page.goto(server_url)
        ParticipantPage(page).join("NotifFreshJoiner")
        # ws.onopen sees permission !== 'default' → button stays hidden
        expect(page.locator("#notif-btn")).to_be_hidden()
        browser.close()

    def test_notif_btn_visible_for_returning_participant(self, server_url, playwright):
        """Auto-joining participant (saved name in localStorage) sees the 🔔
        button when notification permission has not yet been decided."""
        browser = playwright.chromium.launch()
        ctx = browser.new_context()
        # Headless Chromium always reports 'denied'; mock it to 'default'
        # so the ws.onopen guard (=== 'default') fires as it would in a real browser.
        ctx.add_init_script(
            "Object.defineProperty(Notification, 'permission', { get: () => 'default', configurable: true });"
        )
        page = ctx.new_page()
        page.goto(server_url)
        # Simulate returning participant by seeding localStorage, then reload
        page.evaluate("localStorage.setItem('workshop_participant_name', 'ReturningUser')")
        page.reload()
        # After auto-join ws.onopen fires and sees permission === 'default' → show button
        expect(page.locator("#notif-btn")).to_be_visible(timeout=5000)
        browser.close()

    def test_no_spurious_notification_on_join_mid_poll(self, server_url, playwright):
        """Joining while a poll is already active must NOT fire a notification
        (first state message seeds tracking state, doesn't trigger)."""
        _api(server_url, "post", "/api/poll",
             json={"question": "Notif test Q", "options": ["A", "B"]})
        _api(server_url, "put", "/api/poll/status", json={"open": True})

        try:
            browser = playwright.chromium.launch()
            ctx = browser.new_context(permissions=["notifications"])

            # Inject Notification mock BEFORE page load using add_init_script.
            # Also force document.hidden=true so notifyIfHidden() doesn't suppress
            # the notification before it reaches new Notification() — this is what
            # makes the test actually fail without the _stateInitialised guard.
            ctx.add_init_script("""
              window._notifFired = false;
              const _OrigNotif = window.Notification;
              window.Notification = function(t, o) {
                window._notifFired = true;
                return new _OrigNotif(t, o);
              };
              Object.defineProperty(window.Notification, 'permission', {
                get: () => _OrigNotif.permission
              });
              window.Notification.requestPermission = _OrigNotif.requestPermission.bind(_OrigNotif);
              // Force tab to appear hidden so notifyIfHidden() doesn't bail early
              Object.defineProperty(document, 'hidden', { get: () => true, configurable: true });
            """)

            page = ctx.new_page()
            page.goto(server_url)
            ParticipantPage(page).join("NotifJoinMid")
            # Wait for the poll to render — proves the state message was processed
            expect(page.locator("#content h2")).to_be_visible(timeout=5000)

            notif_fired = page.evaluate("window._notifFired")
            assert not notif_fired, "No notification should fire when joining mid-poll"
            browser.close()
        finally:
            _api(server_url, "put", "/api/poll/status", json={"open": False})
            _api(server_url, "delete", "/api/poll")
