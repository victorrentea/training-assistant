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

import requests
import pytest
from playwright.sync_api import Page, expect, sync_playwright

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage

PROD_URL = "https://interact.victorrentea.ro"
PROD_HOST_USER = os.environ.get("HOST_USERNAME", "host")
PROD_HOST_PASS = os.environ.get("HOST_PASSWORD", "host")

HOST_USER = "host"
HOST_PASS = "hostvibe!"


# ---------------------------------------------------------------------------
# Server fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def server_url():
    """
    Spin up uvicorn on port 0 (OS picks a free port atomically).
    Parse the actual bound port from uvicorn's stderr output.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", "0"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=os.path.dirname(os.path.abspath(__file__)),
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
    import base64
    browser, ctx = _host_browser_ctx(server_url, playwright)
    # Inject Basic Auth header for all JS fetch() calls BEFORE creating the page
    # (Playwright http_credentials only applies to navigation, not JS-initiated fetch)
    auth_header = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    ctx.add_init_script(f"""
        const _origFetch = window.fetch;
        window.fetch = (input, init = {{}}) => {{
            init.headers = Object.assign({{'Authorization': 'Basic {auth_header}'}}, init.headers || {{}});
            return _origFetch(input, init);
        }};
    """)
    page = ctx.new_page()
    page.on("console", lambda msg: print(f"[browser:{msg.type}] {msg.text}"))
    page.on("response", lambda r: print(f"[network] {r.request.method} {r.url} -> {r.status}") if "/api/" in r.url else None)
    page.goto("/host")
    print(f"[host-fixture] page title after goto: {page.title()!r}, url: {page.url!r}")
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
# TestNameUniqueness
# ---------------------------------------------------------------------------

class TestNameUniqueness:

    def test_duplicate_name_rejected_and_error_shown(self, server_url, playwright):
        browser = playwright.chromium.launch()
        ctx1 = browser.new_context(base_url=server_url)
        ctx2 = browser.new_context(base_url=server_url)

        p1 = ParticipantPage(ctx1.new_page())
        p2 = ParticipantPage(ctx2.new_page())

        p1._page.goto("/")
        p1.join("Frodo")

        p2._page.goto("/")
        p2._page.fill("#name-input", "frodo")  # same name, different case
        p2._page.click("#join-btn")

        expect(p2._page.locator("#join-screen")).to_be_visible(timeout=5000)
        expect(p2._page.locator("#main-screen")).not_to_be_visible()
        expect(p2._page.locator("#join-error")).to_be_visible(timeout=3000)
        expect(p2._page.locator("#join-error")).to_contain_text("already taken")

        ctx1.close()
        ctx2.close()
        browser.close()

    def test_autojoin_with_saved_name_no_js_error(self, server_url, playwright):
        browser = playwright.chromium.launch()
        ctx = browser.new_context(base_url=server_url)
        page = ctx.new_page()

        js_errors = []
        page.on("pageerror", lambda e: js_errors.append(str(e)))

        page.goto("/")
        page.evaluate("localStorage.setItem('workshop_participant_name', 'AutoJoiner')")
        page.reload()

        expect(page.locator("#main-screen")).to_be_visible(timeout=5000)
        assert js_errors == [], f"JS errors on auto-join: {js_errors}"

        ctx.close()
        browser.close()


# ---------------------------------------------------------------------------
# TestRegressions
# ---------------------------------------------------------------------------

class TestRegressions:

    def test_participant_page_loads_with_zero_votes(self, host: HostPage, pax: ParticipantPage):
        """Regression: largestRemainder([0,0,...]) threw TypeError when poll had no votes."""
        js_errors = []
        pax._page.on("pageerror", lambda e: js_errors.append(str(e)))

        pax.join("Grace")
        host.create_poll("Zero votes test?", ["Yes", "No", "Maybe", "Skip"])

        expect(pax._page.locator("#content h2")).to_have_text("Zero votes test?", timeout=5000)
        assert js_errors == [], f"JS errors on participant page: {js_errors}"


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
# Production smoke tests
# ---------------------------------------------------------------------------

@pytest.mark.prod
class TestProductionSmoke:
    """
    Smoke tests against the live Railway deployment.
    Run with: pytest test_e2e.py -m prod -v
    Requires HOST_USERNAME / HOST_PASSWORD env vars.
    """

    def test_prod_participant_page_accessible(self):
        resp = requests.get(f"{PROD_URL}/", timeout=10)
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "")

    def test_prod_host_page_requires_auth(self):
        resp = requests.get(f"{PROD_URL}/host", timeout=10)
        assert resp.status_code == 401

    def test_prod_host_page_accessible_with_credentials(self):
        resp = requests.get(f"{PROD_URL}/host", auth=(PROD_HOST_USER, PROD_HOST_PASS), timeout=10)
        assert resp.status_code == 200

    def test_prod_api_status_public(self):
        resp = requests.get(f"{PROD_URL}/api/status", timeout=10)
        assert resp.status_code == 200
        assert "participants" in resp.json()

    def test_prod_api_poll_requires_auth(self):
        resp = requests.post(f"{PROD_URL}/api/poll", json={}, timeout=10)
        assert resp.status_code == 401
