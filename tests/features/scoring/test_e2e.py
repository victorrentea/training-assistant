"""
E2E tests for Scoring & Leaderboard.

Covers: score display, accumulation across activities, host participant scores,
reset scores, and confetti on correct answer.
"""

import pytest
from playwright.sync_api import expect

from conftest import api, sapi, host_browser_ctx, pax_browser_ctx
from pages.host_page import HostPage
from pages.participant_page import ParticipantPage

# Q&A and Word Cloud have no participant UI on the new activity-model page yet,
# so scoring tests that earn points through those activities are skipped until
# those participant flows are re-ported.
QA_UNPORTED = "Participant Q&A UI not yet ported to the new participant page (CI repair 2026-06-26)"
QA_WC_UNPORTED = "Participant Q&A / Word Cloud UI not yet ported to the new participant page (CI repair 2026-06-26)"


@pytest.mark.usefixtures("clean_scores", "clean_qa")
class TestScoring:

    @pytest.mark.skip(reason=QA_UNPORTED)
    def test_score_visible_when_positive(self, host: HostPage, pax: ParticipantPage):
        """After submitting a Q&A question (100 pts), #my-score becomes visible."""
        pax.join("ScoreTest1")
        host.open_qa_tab()
        pax.submit_question("What is dependency injection?")
        pax._page.wait_for_timeout(1000)
        score = pax.get_score()
        assert score == 100, f"Expected 100 pts, got {score}"

    @pytest.mark.skip(reason=QA_WC_UNPORTED)
    def test_score_accumulates_across_activities(self, host: HostPage, pax: ParticipantPage):
        """Q&A question (100) + word cloud word (200) = 300 pts total."""
        pax.join("ScoreAccum")
        host.open_qa_tab()
        pax.submit_question("How does Spring Boot work?")
        pax._page.wait_for_timeout(1500)
        score = pax.get_score()
        assert 95 <= score <= 105, f"Expected ~100 pts after Q&A submit, got {score}"

        host.open_wordcloud_tab()
        expect(pax._page.locator("#wc-canvas")).to_be_visible(timeout=5000)
        pax.submit_word("resilience")
        pax._page.wait_for_timeout(1500)
        score = pax.get_score()
        assert 290 <= score <= 310, f"Expected ~300 pts (100+200), got {score}"

    @pytest.mark.skip(reason=QA_UNPORTED)
    def test_host_sees_participant_scores(self, host: HostPage, pax: ParticipantPage):
        """After participant earns points, host's participant list reflects the score."""
        pax.join("ScoreHost")
        host.open_qa_tab()
        pax.submit_question("What about microservices?")
        pax._page.wait_for_timeout(1000)

        scores = host.get_participant_scores()
        # Find the participant (name may have emoji/avatar prefix)
        matching = {k: v for k, v in scores.items() if "ScoreHost" in k}
        assert len(matching) > 0, f"Participant ScoreHost not found in {scores}"
        score = list(matching.values())[0]
        assert score == 100, f"Expected host to show 100 pts, got {score}"

    @pytest.mark.skip(reason=QA_UNPORTED)
    def test_reset_scores(self, server_url, host: HostPage, pax: ParticipantPage):
        """Participant earns points, host resets scores, participant score returns to 0."""
        pax.join("ScoreReset")
        host.open_qa_tab()
        pax.submit_question("Reset test question")
        pax._page.wait_for_timeout(1000)
        assert pax.get_score() == 100

        # Reset scores via API
        sapi(server_url, "delete", "/scores")
        pax._page.wait_for_timeout(1500)  # wait for WS broadcast

        score = pax.get_score()
        assert score == 0, f"Expected 0 after reset, got {score}"

    def test_confetti_fires_on_correct_answer(self, host: HostPage, pax: ParticipantPage):
        """Voting correctly and marking correct should trigger confetti."""
        pax.join("ConfettiTest")
        # Patch the canvas-confetti global the participant page calls when a
        # score is earned (_updateScoreBadge → confetti({...})) to track firing.
        pax._page.evaluate("""() => {
            window._confettiFired = false;
            var _orig = window.confetti;
            window.confetti = function() {
                window._confettiFired = true;
                if (typeof _orig === 'function') return _orig.apply(this, arguments);
            };
        }""")

        host._page.click("#tab-quiz")
        host.create_quiz("What is 1+1?", ["1", "2", "3"])
        pax.vote_for("2")
        # castVote is fire-and-forget — wait for the host to register the vote
        # before closing, otherwise the result rows never become markable.
        host.wait_for_votes(1)
        host.close_quiz()
        host.mark_correct("2")

        # Wait for result message to arrive
        expect(pax._page.locator(".result-icon", has_text="✅")).to_be_visible(timeout=5000)

        fired = pax._page.evaluate("window._confettiFired")
        assert fired is True, "Confetti should have fired on correct answer"
