"""
End-to-end browser tests using Playwright.

Spins up a real uvicorn server on a free port, then drives the host and
participant UIs through Chromium (headless).

Run:
    pytest test_e2e.py -v
    pytest test_e2e.py -v --headed        # watch the browsers
"""

import os
import re
import socket
import subprocess
import sys
import time

import requests

import pytest
from playwright.sync_api import Page, expect, sync_playwright

PROD_URL = "https://interact.victorrentea.ro"
PROD_HOST_USER = os.environ.get("HOST_USERNAME", "host")
PROD_HOST_PASS = os.environ.get("HOST_PASSWORD", "host")


# ---------------------------------------------------------------------------
# Server fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def server_url():
    """
    Spin up uvicorn on port 0 (OS picks a free port atomically).
    Parse the actual bound port from uvicorn's stderr output.
    This avoids the TOCTOU race of pick-port-then-bind.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", "0"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,   # capture to read bound port
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )

    # uvicorn logs: "Uvicorn running on http://127.0.0.1:<PORT>"
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

    # Drain stderr in background so the pipe doesn't block
    import threading
    threading.Thread(target=proc.stderr.read, daemon=True).start()

    yield f"http://127.0.0.1:{port}"

    proc.terminate()
    proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

HOST_USER = "host"
HOST_PASS = "hostvibe!"
HOST_AUTH = (HOST_USER, HOST_PASS)


def host_context(server_url, playwright):
    """Create a browser context pre-configured with host Basic Auth credentials."""
    browser = playwright.chromium.launch()
    ctx = browser.new_context(
        base_url=server_url,
        http_credentials={"username": HOST_USER, "password": HOST_PASS},
    )
    return browser, ctx


def api(server_url, method, path, **kwargs):
    """Make an authenticated API call to a host-only endpoint."""
    return getattr(requests, method)(f"{server_url}{path}", auth=HOST_AUTH, **kwargs)


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def host_page(server_url, playwright):
    browser, ctx = host_context(server_url, playwright)
    page = ctx.new_page()
    page.goto("/host")
    yield page
    ctx.close()
    browser.close()


@pytest.fixture()
def participant_page(server_url, playwright):
    browser = playwright.chromium.launch()
    ctx = browser.new_context(base_url=server_url)
    page = ctx.new_page()
    page.goto("/")
    yield page
    ctx.close()
    browser.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def join_as(page: Page, name: str):
    page.fill("#name-input", name)
    page.click("#join-btn")
    expect(page.locator("#main-screen")).to_be_visible(timeout=5000)


def host_create_and_open_poll(host: Page, question: str, options: list[str], multi=False):
    """Type a poll into the composer and launch it."""
    composer = host.locator("#poll-input")
    composer.click()
    # Select all and replace
    composer.evaluate("el => { el.focus(); document.execCommand('selectAll'); }")
    text = "\n".join([question] + options)
    host.keyboard.type(text)
    if multi:
        host.check("#multi-check")
    host.click("#create-btn")
    # Poll should become active — "Close voting" button appears
    expect(host.locator("text=Close voting")).to_be_visible(timeout=5000)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPollLifecycle:

    def test_participant_sees_poll_after_host_creates_it(
        self, server_url, playwright
    ):
        browser = playwright.chromium.launch()
        _, host_ctx = host_context(server_url, playwright)
        pax_ctx = browser.new_context(base_url=server_url)

        host = host_ctx.new_page()
        pax = pax_ctx.new_page()

        host.goto("/host")
        pax.goto("/")
        join_as(pax, "Alice")

        host_create_and_open_poll(host, "Favourite language?", ["Python", "Java", "Go"])

        # Participant should see the question
        expect(pax.locator("#content h2")).to_have_text("Favourite language?", timeout=5000)
        # All three options visible
        expect(pax.locator(".option-btn")).to_have_count(3)

        host_ctx.close()
        pax_ctx.close()
        browser.close()

    def test_vote_registers_and_host_sees_count(self, server_url, playwright):
        browser = playwright.chromium.launch()
        _, host_ctx = host_context(server_url, playwright)
        pax_ctx = browser.new_context(base_url=server_url)

        host = host_ctx.new_page()
        pax = pax_ctx.new_page()

        host.goto("/host")
        pax.goto("/")
        join_as(pax, "Bob")

        host_create_and_open_poll(host, "Best DB?", ["Postgres", "MySQL", "SQLite"])

        # Participant votes for first option
        pax.locator(".option-btn").first.click()
        expect(pax.locator(".vote-msg")).to_contain_text("Vote registered", timeout=5000)

        # Host sees 1 total vote
        expect(host.locator("text=1 total vote")).to_be_visible(timeout=5000)

        host_ctx.close()
        pax_ctx.close()
        browser.close()

    def test_results_shown_after_poll_closed(self, server_url, playwright):
        browser = playwright.chromium.launch()
        _, host_ctx = host_context(server_url, playwright)
        pax_ctx = browser.new_context(base_url=server_url)

        host = host_ctx.new_page()
        pax = pax_ctx.new_page()

        host.goto("/host")
        pax.goto("/")
        join_as(pax, "Carol")

        host_create_and_open_poll(host, "Best cloud?", ["AWS", "GCP", "Azure"])

        # Vote
        pax.locator(".option-btn").first.click()
        expect(pax.locator(".vote-msg")).to_contain_text("Vote registered", timeout=5000)

        # Host closes poll
        host.click("text=Close voting")
        expect(host.locator("text=Re-open")).to_be_visible(timeout=5000)

        # Participant sees percentages (poll closed → bars visible)
        expect(pax.locator(".pct").first).to_be_visible(timeout=5000)
        expect(pax.locator(".closed-banner")).to_be_visible(timeout=5000)

        host_ctx.close()
        pax_ctx.close()
        browser.close()

    def test_correct_answer_feedback_shown_to_participant(self, server_url, playwright):
        browser = playwright.chromium.launch()
        _, host_ctx = host_context(server_url, playwright)
        pax_ctx = browser.new_context(base_url=server_url)

        host = host_ctx.new_page()
        pax = pax_ctx.new_page()

        host.goto("/host")
        pax.goto("/")
        join_as(pax, "Dave")

        host_create_and_open_poll(host, "Capital of France?", ["Berlin", "Paris", "Rome"])

        # Vote for the correct answer (Paris = index 1)
        pax.locator(".option-btn").nth(1).click()
        expect(pax.locator(".vote-msg")).to_contain_text("Vote registered", timeout=5000)

        # Close poll
        host.click("text=Close voting")
        expect(host.locator("text=Re-open")).to_be_visible(timeout=5000)

        # Host marks Paris (index 1) as correct
        host.locator(".result-row").nth(1).click()
        # Participant sees a ✅ icon
        expect(pax.locator(".result-icon", has_text="✅")).to_be_visible(timeout=5000)

        host_ctx.close()
        pax_ctx.close()
        browser.close()


class TestMultiSelect:

    def test_correct_count_hint_shown_to_participant(self, server_url, playwright):
        browser = playwright.chromium.launch()
        _, host_ctx = host_context(server_url, playwright)
        pax_ctx = browser.new_context(base_url=server_url)

        host = host_ctx.new_page()
        pax = pax_ctx.new_page()

        host.goto("/host")
        pax.goto("/")
        join_as(pax, "Eve")

        host_create_and_open_poll(
            host, "JVM languages?", ["Java", "Kotlin", "Python", "Scala"],
            multi=True
        )
        # Default correct-count is 2; hint must mention it
        expect(pax.locator(".vote-msg").first).to_contain_text(
            "exactly 2", timeout=5000
        )

        host_ctx.close()
        pax_ctx.close()
        browser.close()

    def test_participant_cannot_select_more_than_correct_count(
        self, server_url, playwright
    ):
        browser = playwright.chromium.launch()
        _, host_ctx = host_context(server_url, playwright)
        pax_ctx = browser.new_context(base_url=server_url)

        host = host_ctx.new_page()
        pax = pax_ctx.new_page()

        host.goto("/host")
        pax.goto("/")
        join_as(pax, "Frank")

        host_create_and_open_poll(
            host, "Pick 2 fruits?", ["Apple", "Banana", "Cherry", "Date"],
            multi=True
        )
        # correct_count defaults to 2; select first two
        pax.locator(".option-btn").nth(0).click()
        pax.locator(".option-btn").nth(1).click()
        # Third button must be disabled
        expect(pax.locator(".option-btn").nth(2)).to_be_disabled(timeout=3000)
        expect(pax.locator(".option-btn").nth(3)).to_be_disabled(timeout=3000)

        host_ctx.close()
        pax_ctx.close()
        browser.close()


class TestNameUniqueness:

    def test_duplicate_name_rejected_and_error_shown(self, server_url, playwright):
        """
        When a participant tries to join with a name already taken,
        they should stay on the join screen and see an error message.
        """
        browser = playwright.chromium.launch()
        ctx1 = browser.new_context(base_url=server_url)
        ctx2 = browser.new_context(base_url=server_url)

        pax1 = ctx1.new_page()
        pax2 = ctx2.new_page()

        pax1.goto("/")
        join_as(pax1, "Frodo")

        pax2.goto("/")
        pax2.fill("#name-input", "frodo")  # same name, different case
        pax2.click("#join-btn")

        # pax2 should remain on join screen
        expect(pax2.locator("#join-screen")).to_be_visible(timeout=5000)
        expect(pax2.locator("#main-screen")).not_to_be_visible()
        # Error message shown
        expect(pax2.locator("#join-error")).to_be_visible(timeout=3000)
        expect(pax2.locator("#join-error")).to_contain_text("already taken")

        ctx1.close()
        ctx2.close()
        browser.close()

    def test_autojoin_with_saved_name_no_js_error(self, server_url, playwright):
        """
        Regression: _joinedWithSuggestion declared after join() is called on
        page load when localStorage has a saved name → TDZ ReferenceError.
        """
        browser = playwright.chromium.launch()
        ctx = browser.new_context(base_url=server_url)
        page = ctx.new_page()

        js_errors = []
        page.on("pageerror", lambda e: js_errors.append(str(e)))

        # Pre-set localStorage so the page auto-joins on load
        page.goto("/")
        page.evaluate("localStorage.setItem('workshop_participant_name', 'AutoJoiner')")
        page.reload()

        # Should reach main screen without JS errors
        expect(page.locator("#main-screen")).to_be_visible(timeout=5000)
        assert js_errors == [], f"JS errors on auto-join: {js_errors}"

        ctx.close()
        browser.close()


class TestRegressions:

    def test_participant_page_loads_with_zero_votes(self, server_url, playwright):
        """
        Regression: largestRemainder([0,0,...]) threw TypeError when poll had
        no votes yet. Participant joining an open poll must render without error.
        """
        browser = playwright.chromium.launch()
        _, host_ctx = host_context(server_url, playwright)
        pax_ctx = browser.new_context(base_url=server_url)

        host = host_ctx.new_page()
        pax = pax_ctx.new_page()

        # Capture JS errors on participant page
        js_errors = []
        pax.on("pageerror", lambda e: js_errors.append(str(e)))

        host.goto("/host")
        pax.goto("/")
        join_as(pax, "Grace")

        # Host creates a poll — participant page renders with 0 votes
        host_create_and_open_poll(host, "Zero votes test?", ["Yes", "No", "Maybe", "Skip"])

        # Give the state message time to arrive and render
        expect(pax.locator("#content h2")).to_have_text("Zero votes test?", timeout=5000)

        # No JS errors must have occurred
        assert js_errors == [], f"JS errors on participant page: {js_errors}"

        host_ctx.close()
        pax_ctx.close()
        browser.close()


class TestWordCloud:

    def test_host_opens_wordcloud_participant_sees_screen(
        self, server_url, playwright
    ):
        browser = playwright.chromium.launch()
        pax_ctx = browser.new_context(base_url=server_url)
        pax = pax_ctx.new_page()
        pax.goto("/")
        join_as(pax, "WcTester1")

        # Clear any leftover poll state so word cloud is not blocked
        resp = api(server_url, "delete", "/api/poll")
        assert resp.status_code == 200

        # Host opens word cloud via direct API call
        resp = api(server_url, "post", "/api/wordcloud/status", json={"active": True})
        assert resp.status_code == 200

        # Participant sees word cloud canvas
        expect(pax.locator("#wc-canvas")).to_be_visible(timeout=5000)

        # Cleanup: close word cloud after test
        resp = api(server_url, "post", "/api/wordcloud/status", json={"active": False})
        assert resp.status_code == 200

        pax_ctx.close()
        browser.close()

    def test_participant_submits_word_appears_in_my_words(
        self, server_url, playwright
    ):
        browser = playwright.chromium.launch()
        pax_ctx = browser.new_context(base_url=server_url)
        pax = pax_ctx.new_page()
        pax.goto("/")
        join_as(pax, "WcTester2")

        # Ensure wordcloud is active (may still be active from previous test)
        resp = api(server_url, "post", "/api/wordcloud/status", json={"active": False})
        assert resp.status_code == 200
        resp = api(server_url, "post", "/api/wordcloud/status", json={"active": True})
        assert resp.status_code == 200

        expect(pax.locator("#wc-canvas")).to_be_visible(timeout=5000)

        pax.fill("#wc-input", "microservices")
        pax.click("#wc-go")

        # Word appears in the participant's own submitted words list
        expect(pax.locator("#wc-my-words li")).to_have_count(1, timeout=3000)
        expect(pax.locator("#wc-my-words li").first).to_have_text("microservices")

        # Cleanup: close word cloud after test
        resp = api(server_url, "post", "/api/wordcloud/status", json={"active": False})
        assert resp.status_code == 200

        pax_ctx.close()
        browser.close()

    def test_close_wordcloud_participant_returns_to_idle(
        self, server_url, playwright
    ):
        browser = playwright.chromium.launch()
        pax_ctx = browser.new_context(base_url=server_url)
        pax = pax_ctx.new_page()
        pax.goto("/")
        join_as(pax, "WcTester3")

        # Ensure wordcloud is active
        resp = api(server_url, "post", "/api/wordcloud/status", json={"active": False})
        assert resp.status_code == 200
        resp = api(server_url, "post", "/api/wordcloud/status", json={"active": True})
        assert resp.status_code == 200

        expect(pax.locator("#wc-canvas")).to_be_visible(timeout=5000)

        # Host closes word cloud
        resp = api(server_url, "post", "/api/wordcloud/status", json={"active": False})
        assert resp.status_code == 200

        # Participant no longer sees word cloud canvas
        expect(pax.locator("#wc-canvas")).not_to_be_visible(timeout=5000)

        pax_ctx.close()
        browser.close()


# ---------------------------------------------------------------------------
# Production smoke tests (run against live deployed instance)
# ---------------------------------------------------------------------------

@pytest.mark.prod
class TestProductionSmoke:
    """
    Smoke tests against the live Railway deployment.
    Run with: pytest test_e2e.py -m prod -v
    Requires HOST_USERNAME / HOST_PASSWORD env vars to match Railway config.
    """

    def test_prod_participant_page_accessible(self):
        resp = requests.get(f"{PROD_URL}/", timeout=10)
        assert resp.status_code == 200, f"Participant page returned {resp.status_code}"
        assert "html" in resp.headers.get("content-type", "")

    def test_prod_host_page_requires_auth(self):
        resp = requests.get(f"{PROD_URL}/host", timeout=10)
        assert resp.status_code == 401, f"Expected 401 without auth, got {resp.status_code}"

    def test_prod_host_page_accessible_with_credentials(self):
        resp = requests.get(f"{PROD_URL}/host", auth=(PROD_HOST_USER, PROD_HOST_PASS), timeout=10)
        assert resp.status_code == 200, (
            f"Host page returned {resp.status_code} with {PROD_HOST_USER!r} — "
            "check HOST_USERNAME / HOST_PASSWORD env vars on Railway"
        )

    def test_prod_api_status_public(self):
        resp = requests.get(f"{PROD_URL}/api/status", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert "participants" in data

    def test_prod_api_poll_requires_auth(self):
        resp = requests.post(f"{PROD_URL}/api/poll", json={}, timeout=10)
        assert resp.status_code == 401, f"Expected 401 without auth, got {resp.status_code}"
