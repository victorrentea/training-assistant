"""
Hermetic E2E test: Poll voting, results display, and scoring.

Verifies:
1. Participants can vote in polls and see correct results
2. Correct voters receive points (visible in UI)
3. Wrong voters receive zero points
4. Scores persist after page refresh (reads from REST state, not just WS)
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

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


@pytest.mark.nightly
def test_poll_vote_results_and_scoring():
    """Full poll flow: create → vote → close → reveal correct → verify scores."""
    session_id = fresh_session("PollScoring")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Host
        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_raw = host_ctx.new_page()
        host_raw.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_raw.locator("#tab-poll")).to_be_visible(timeout=10000)
        host = HostPage(host_raw)

        # Participant 1 (will vote correctly)
        pax1_ctx = browser.new_context()
        pax1_raw = pax1_ctx.new_page()
        pax1_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax1 = ParticipantPage(pax1_raw)
        pax1.join("Alice")

        # Participant 2 (will vote wrong)
        pax2_ctx = browser.new_context()
        pax2_raw = pax2_ctx.new_page()
        pax2_raw.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax2 = ParticipantPage(pax2_raw)
        pax2.join("Bob")

        # ── Step 1: Host creates and opens poll ──
        host.create_poll("What is 2+2?", ["3", "4", "5"])
        print("Step 1 OK: Poll created and opened")

        # ── Step 2: Participants see poll ──
        for _name, pax in [("Alice", pax1), ("Bob", pax2)]:
            expect(pax._page.locator("#content h2")).to_have_text(
                "What is 2+2?", timeout=5000
            )
            expect(pax._page.locator(".option-btn")).to_have_count(3)
        print("Step 2 OK: Both participants see the poll")

        # ── Step 3: Participants vote ──
        pax1.vote_for("4")  # correct
        pax2.vote_for("3")  # wrong
        print("Step 3 OK: Alice voted 4 (correct), Bob voted 3 (wrong)")

        # ── Step 4: Host closes poll ──
        host.close_poll()
        print("Step 4 OK: Poll closed")

        # ── Step 5: Participants see results with percentages ──
        for pax in [pax1, pax2]:
            expect(pax._page.locator(".closed-banner")).to_be_visible(timeout=5000)
        pcts = pax1.get_percentages()
        assert pcts == [50, 50, 0], f"Expected [50, 50, 0] but got {pcts}"
        print(f"Step 5 OK: Results visible, percentages = {pcts}")

        # ── Step 6: Host reveals correct answer (option B = "4") ──
        host.reveal_correct(["B"])
        print("Step 6 OK: Correct answer revealed")

        # ── Step 7: Correct voter (Alice) gets points ──
        pax1_raw.wait_for_timeout(1000)  # wait for WS score update
        alice_score = pax1.get_score()
        assert alice_score > 0, f"Alice should have points but got {alice_score}"
        print(f"Step 7 OK: Alice scored {alice_score} points")

        # ── Step 8: Wrong voter (Bob) gets zero points ──
        bob_score = pax2.get_score()
        assert bob_score == 0, f"Bob should have 0 points but got {bob_score}"
        print("Step 8 OK: Bob has 0 points")

        # ── Step 9: Score persists after page refresh ──
        pax1_raw.reload(wait_until="networkidle")
        pax1_raw.wait_for_timeout(2000)  # wait for WS reconnect + state
        alice_score_after = pax1.get_score()
        assert alice_score_after == alice_score, (
            f"Alice's score should persist after refresh: expected {alice_score}, "
            f"got {alice_score_after}"
        )
        print(f"Step 9 OK: Alice's score persists after refresh ({alice_score_after})")

        # ── Step 10: Host sees correct scores in participant list ──
        host_scores = host.get_participant_scores()
        print(f"Host sees scores: {host_scores}")
        # Find Alice and Bob by name
        alice_host_score = host_scores.get("Alice", -1)
        bob_host_score = host_scores.get("Bob", -1)
        assert alice_host_score > 0, f"Host should see Alice with points, got {alice_host_score}"
        assert bob_host_score == 0, f"Host should see Bob with 0 points, got {bob_host_score}"
        print("Step 10 OK: Host sees correct scores in participant list")

        print("SUCCESS: Poll voting, results, and scoring all work correctly!")
        browser.close()
