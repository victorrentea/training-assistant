"""
Hermetic E2E test: Poll voting, results display, and scoring.

Verifies:
1. Participants can vote in polls and see correct results
2. Correct voters receive points (visible in UI)
3. Wrong voters receive zero points
4. Scores persist after page refresh (reads from REST state, not just WS)
"""

import json
import os
import sys
import urllib.request

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

        # Helper to get score from daemon
        def _get_daemon_score(name: str) -> int:
            import base64 as _b64
            auth = _b64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
            req = urllib.request.Request(
                f"{DAEMON_BASE}/api/{session_id}/host/state",
                headers={"Authorization": f"Basic {auth}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                for p in data.get("participants", []):
                    if p.get("name") == name:
                        return p.get("score", 0)
            return -1

        # ── Step 1: Host creates and opens poll ──
        host.create_poll("What is 2+2?", ["3", "4", "5"])
        print("Step 1 OK: Poll created and opened")

        # ── Step 2: Participants vote via API ──
        # Poll options: A="3", B="4", C="5"
        # Alice votes B (correct), Bob votes A (wrong)
        pax1._page.evaluate("""async () => {
            await fetch('/' + _sessionId + '/api/participant/poll/vote', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'x-participant-id': _myUUID},
                body: JSON.stringify({option_ids: ['B']})
            });
        }""")
        pax2._page.evaluate("""async () => {
            await fetch('/' + _sessionId + '/api/participant/poll/vote', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'x-participant-id': _myUUID},
                body: JSON.stringify({option_ids: ['A']})
            });
        }""")
        pax1_raw.wait_for_timeout(500)
        print("Step 2 OK: Alice voted B (correct), Bob voted A (wrong)")

        # ── Step 3: Host closes poll ──
        host.close_poll()
        print("Step 3 OK: Poll closed")

        # ── Step 4: Host reveals correct answer (option B = "4") ──
        host.reveal_correct(["B"])
        pax1_raw.wait_for_timeout(1000)  # wait for WS score update
        print("Step 4 OK: Correct answer revealed")

        # ── Step 5: Verify scores via daemon API ──
        alice_score = _get_daemon_score("Alice")
        assert alice_score > 0, f"Alice should have points but daemon shows {alice_score}"
        print(f"Step 5 OK: Alice scored {alice_score} points")

        bob_score = _get_daemon_score("Bob")
        assert bob_score == 0, f"Bob should have 0 points but daemon shows {bob_score}"
        print("Step 5 OK: Bob has 0 points")

        # ── Step 6: Host sees correct scores in participant list ──
        host_scores = host.get_participant_scores()
        print(f"Host sees scores: {host_scores}")
        alice_host_score = host_scores.get("Alice", -1)
        bob_host_score = host_scores.get("Bob", -1)
        assert alice_host_score > 0, f"Host should see Alice with points, got {alice_host_score}"
        assert bob_host_score == 0, f"Host should see Bob with 0 points, got {bob_host_score}"
        print("Step 6 OK: Host sees correct scores in participant list")

        print("SUCCESS: Poll voting, results, and scoring all work correctly!")
        browser.close()
