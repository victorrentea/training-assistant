"""Hermetic E2E: full poll lifecycle with two participants.

Mirrors the test_quiz_scoring.py pattern (Playwright + real backend +
daemon + page-object helpers). Marked nightly because it spins up
multiple browser contexts and exercises several WS round-trips.
"""
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest  # noqa: I001
from playwright.sync_api import expect, sync_playwright

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage
from session_utils import fresh_session

HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "host")
BASE = "http://localhost:8000"
DAEMON_BASE = "http://localhost:1234"


@pytest.mark.nightly
def test_poll_full_lifecycle_with_two_participants():
    """Draft → live → stop → clear, then a second poll with a late joiner.

    The draft (options, multi, public) freezes when the host presses Start, so
    participants never see the question change under them (0dcd28d7): every choice
    is made before Start, and what moves while the poll runs is the votes.
    """
    session_id = fresh_session("PollE2E")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ── Host
        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_raw = host_ctx.new_page()
        host_raw.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_raw)

        # ── Alice
        alice_ctx = browser.new_context()
        alice_raw = alice_ctx.new_page()
        alice_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        alice = ParticipantPage(alice_raw)
        alice.join("Alice")

        # ── Poll 1: single pick, private ─────────────────────────────────────
        host.open_poll_tab()
        host.fill_poll_question("How was the demo?")
        host.add_poll_option("A")
        host.add_poll_option("B")
        host.add_poll_option("C")
        host.set_poll_public(False)
        host.start_poll()
        host.expect_poll_draft_locked()

        alice.wait_for_poll()
        assert alice.poll_question_text() == "How was the demo?"
        assert alice.poll_options_count() == 3
        assert "Pick one" in alice.poll_status_text()

        # Alice votes A, then changes her mind to B; a private poll shows no counts.
        alice.cast_poll_vote(0)
        alice_raw.wait_for_timeout(500)
        assert alice.poll_option_is_selected(0)
        alice.cast_poll_vote(1)
        alice_raw.wait_for_timeout(500)
        assert alice.poll_option_is_selected(1)
        assert not alice.poll_option_is_selected(0)
        assert alice.poll_option_count(1) is None

        # Stop freezes the votes and reveals the tally, even for a private poll.
        host.stop_poll()
        expect(alice_raw.locator("#poll-status-bar")).to_have_text("Voting ended", timeout=5000)
        assert alice.poll_option_count(1) == 1
        assert alice.poll_option_count(0) == 0
        assert alice.poll_option_is_selected(1)

        host.clear_poll()
        expect(alice_raw.locator("#activity-poll-section")).to_be_hidden(timeout=5000)

        # ── Poll 2: multi-select, public, with a late joiner ─────────────────
        host.fill_poll_question("Which did you use?")
        host.add_poll_option("X")
        host.add_poll_option("Y")
        host.add_poll_option("Z")
        host.set_poll_multi(True)
        host.set_poll_public(True)
        host.start_poll()

        alice.wait_for_poll()
        assert alice.poll_question_text() == "Which did you use?"
        assert "Pick as many" in alice.poll_status_text()
        alice.cast_poll_vote(1)
        alice.cast_poll_vote(2)
        alice_raw.wait_for_timeout(500)
        assert alice.poll_option_is_selected(1)
        assert alice.poll_option_is_selected(2)
        # Public: live counts.
        assert alice.poll_option_count(0) == 0
        assert alice.poll_option_count(1) == 1
        assert alice.poll_option_count(2) == 1

        bob_ctx = browser.new_context()
        bob_raw = bob_ctx.new_page()
        bob_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        bob = ParticipantPage(bob_raw)
        bob.join("Bob")
        bob.wait_for_poll()
        bob.cast_poll_vote(1)
        bob_raw.wait_for_timeout(500)
        alice_raw.wait_for_timeout(500)

        assert alice.poll_option_count(1) == 2
        assert bob.poll_option_count(1) == 2

        host.clear_poll()
        expect(alice_raw.locator("#activity-poll-section")).to_be_hidden(timeout=5000)
        expect(bob_raw.locator("#activity-poll-section")).to_be_hidden(timeout=5000)

        browser.close()


@pytest.mark.nightly
def test_poll_state_restored_on_participant_refresh():
    session_id = fresh_session("PollRefresh")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(http_credentials={"username": HOST_USER, "password": HOST_PASS})
        host_raw = host_ctx.new_page()
        host_raw.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        host = HostPage(host_raw)

        alice_ctx = browser.new_context()
        alice_raw = alice_ctx.new_page()
        alice_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        alice = ParticipantPage(alice_raw)
        alice.join("Alice")

        host.open_poll_tab()
        host.fill_poll_question("Refresh test?")
        host.add_poll_option("Yes")
        host.add_poll_option("No")
        host.set_poll_public(True)
        host.start_poll()

        alice.wait_for_poll()
        alice.cast_poll_vote(0)
        alice_raw.wait_for_timeout(500)
        assert alice.poll_option_count(0) == 1

        # Refresh Alice's page
        alice_raw.reload(wait_until="networkidle")
        alice.wait_for_poll()

        # State should be restored: her vote on A, counts visible
        assert alice.poll_option_is_selected(0)
        assert alice.poll_option_count(0) == 1
        assert alice.poll_option_count(1) == 0

        browser.close()
