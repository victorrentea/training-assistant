"""
E2E tests for Connection/Reconnection, Quiz edge cases, and Identity edge cases.

Run:
    pytest test_e2e_connection_quiz_identity.py -v
"""

import re
import pytest
from playwright.sync_api import expect

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage
from conftest import api, sapi, host_browser_ctx, pax_browser_ctx, pax_url, host_url

# Q&A has no participant UI on the new activity-model participant page yet, so
# tests that earn points / drive participant Q&A flows are skipped until ported.
QA_UNPORTED = "Participant Q&A UI not yet ported to the new participant page (CI repair 2026-06-26)"
QUIZ_PCT_REMOVED = (
    "Participant quiz UI no longer shows percentage bars (Poll-only display now) "
    "(CI repair 2026-06-26)"
)


# ---------------------------------------------------------------------------
# TestConnectionReconnection
# ---------------------------------------------------------------------------

class TestConnectionReconnection:

    def test_rename_mid_session_host_sees_update(self, host: HostPage, pax: ParticipantPage):
        """Join as 'Alice', rename to 'Bob', host participant list updates."""
        pax.join("Alice")
        # Verify host sees Alice
        expect(host._page.locator("#pax-list")).to_contain_text("Alice", timeout=5000)

        # Rename to Bob via inline edit
        pax.rename("Bob")

        # Host should see "Bob" instead of "Alice"
        expect(host._page.locator("#pax-list")).to_contain_text("Bob", timeout=5000)

    @pytest.mark.skip(reason=QA_UNPORTED)
    @pytest.mark.usefixtures("clean_scores", "clean_qa")
    def test_participant_refresh_preserves_score(self, server_url, playwright):
        """Earn score via Q&A, refresh page, score is preserved after rejoin."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b_pax, ctx_pax = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        pax_page = ctx_pax.new_page()
        pax_page.goto(pax_url())
        pax = ParticipantPage(pax_page)

        try:
            host._page.goto(host_url())
            pax.join("ScoreRefresh")
            host.open_qa_tab()
            pax.submit_question("Refresh test question")
            pax_page.wait_for_timeout(1000)
            assert pax.get_score() == 100

            # Refresh the page (same context = same localStorage)
            pax_page.reload()
            # Auto-rejoin happens because name is in localStorage
            expect(pax_page.locator("#main-screen")).to_be_visible(timeout=10000)
            pax_page.wait_for_timeout(1500)

            score = pax.get_score()
            assert score == 100, f"Expected score 100 after refresh, got {score}"
        finally:
            ctx_host.close()
            ctx_pax.close()
            b_host.close()
            b_pax.close()

    def test_host_multi_tab_kicks_first(self, server_url, playwright):
        """Opening a second host tab kicks the first one."""
        b1, ctx1 = host_browser_ctx(server_url, playwright)
        b2, ctx2 = host_browser_ctx(server_url, playwright)

        page1 = ctx1.new_page()
        page1.goto(host_url())
        # First host is connected — badge has class "connected"
        expect(page1.locator("#ws-badge.connected")).to_be_visible(timeout=5000)

        try:
            # Open second host tab
            page2 = ctx2.new_page()
            page2.goto(host_url())
            expect(page2.locator("#ws-badge.connected")).to_be_visible(timeout=5000)

            # First host should show the kicked overlay
            expect(page1.locator("#kicked-overlay")).to_be_visible(timeout=5000)
        finally:
            ctx1.close()
            ctx2.close()
            b1.close()
            b2.close()

    def test_participant_reconnect_restores_name(self, server_url, playwright):
        """Close and reopen participant page in same context — auto-joins with saved name."""
        b, ctx = pax_browser_ctx(server_url, playwright)

        try:
            page1 = ctx.new_page()
            page1.goto(pax_url())
            pax = ParticipantPage(page1)
            pax.join("ReconTest")

            # Close the page
            page1.close()

            # Open new page in same context (same localStorage)
            page2 = ctx.new_page()
            page2.goto(pax_url())

            # Should auto-join with saved name
            expect(page2.locator("#display-name")).to_be_visible(timeout=10000)
            expect(page2.locator("#display-name .display-name-text")).to_have_text("ReconTest", timeout=5000)
        finally:
            ctx.close()
            b.close()


# ---------------------------------------------------------------------------
# TestQuizEdgeCases
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def clean_quiz(server_url):
    """Clear quiz state before and after each test."""
    sapi(server_url, "put", "/quiz/status", json={"open": False})
    sapi(server_url, "delete", "/quiz")
    yield
    sapi(server_url, "put", "/quiz/status", json={"open": False})
    sapi(server_url, "delete", "/quiz")


@pytest.mark.usefixtures("clean_quiz")
class TestQuizEdgeCases:

    def test_vote_is_final_cannot_change(self, host: HostPage, pax: ParticipantPage):
        """After voting, clicking another option should not change the vote."""
        pax.join("VoteFinal")
        host._page.click("#tab-quiz")
        host.create_quiz("Pick one?", ["Alpha", "Beta", "Gamma"])
        pax.vote_for("Alpha")

        # Try clicking Beta - should not change vote
        pax._page.locator(".option-btn:has-text('Beta')").click()
        pax._page.wait_for_timeout(500)

        # Close quiz so results are visible, then verify only 1 vote total.
        # Wait for the (single) vote to register on the host before closing.
        host.wait_for_votes(1)
        host.close_quiz()
        expect(host._page.locator("text=1 total vote")).to_be_visible(timeout=3000)

    def test_multiple_participants_vote_correct_counts(self, server_url, playwright):
        """3 participants: P1→A, P2→B, P3→A. Host sees 3 total votes.

        The participant quiz UI no longer renders percentage bars (those moved to
        the Poll-only display), so the assertion focuses on the host-side total
        vote count instead.
        """
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)
        b2, ctx2 = pax_browser_ctx(server_url, playwright)
        b3, ctx3 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1 = ParticipantPage(ctx1.new_page())
        p2 = ParticipantPage(ctx2.new_page())
        p3 = ParticipantPage(ctx3.new_page())

        host._page.goto(host_url())
        p1._page.goto(pax_url())
        p2._page.goto(pax_url())
        p3._page.goto(pax_url())

        try:
            p1.join("Voter1")
            p2.join("Voter2")
            p3.join("Voter3")
            host.create_quiz("Best letter?", ["A", "B", "C"])

            p1.vote_for("A")
            p2.vote_for("B")
            p3.vote_for("A")

            # Votes are fire-and-forget — wait for all 3 to register on the host
            # before closing so the result counts are complete.
            host.wait_for_votes(3)
            host.close_quiz()
            expect(host._page.locator("text=3 total vote")).to_be_visible(timeout=5000)
        finally:
            for ctx in (ctx_host, ctx1, ctx2, ctx3):
                ctx.close()
            for b in (b_host, b1, b2, b3):
                b.close()

    @pytest.mark.usefixtures("clean_scores")
    def test_speed_based_scoring_faster_gets_more(self, server_url, playwright):
        """Faster voter gets more points than slower voter."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)
        b2, ctx2 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1 = ParticipantPage(ctx1.new_page())
        p2 = ParticipantPage(ctx2.new_page())

        host._page.goto(host_url())
        p1._page.goto(pax_url())
        p2._page.goto(pax_url())

        try:
            p1.join("FastVoter")
            p2.join("SlowVoter")
            host.create_quiz("Speed test?", ["Right", "Wrong"])

            # P1 votes immediately
            p1.vote_for("Right")
            # Wait 2 seconds then P2 votes
            p2._page.wait_for_timeout(2000)
            p2.vote_for("Right")

            # Wait for both votes to register on the host before closing.
            host.wait_for_votes(2)
            host.close_quiz()
            host.mark_correct("Right")

            # Wait for scores to arrive
            expect(p1._page.locator(".result-icon", has_text="✅")).to_be_visible(timeout=5000)
            expect(p2._page.locator(".result-icon", has_text="✅")).to_be_visible(timeout=5000)

            p1._page.wait_for_timeout(500)
            score1 = p1.get_score()
            score2 = p2.get_score()
            assert score1 > score2, f"Fast voter ({score1}) should score more than slow voter ({score2})"
            assert score1 >= 400, f"Fast voter should get at least 400 pts, got {score1}"
            assert score2 >= 400, f"Slow voter should get at least 400 pts, got {score2}"
        finally:
            for ctx in (ctx_host, ctx1, ctx2):
                ctx.close()
            for b in (b_host, b1, b2):
                b.close()

    @pytest.mark.skip(reason=QUIZ_PCT_REMOVED)
    def test_quiz_with_2_options(self, host: HostPage, pax: ParticipantPage):
        """Minimum option count: quiz with exactly 2 options works."""
        pax.join("TwoOpt")
        host._page.click("#tab-quiz")
        host.create_quiz("Yes or no?", ["Yes", "No"])
        expect(pax._page.locator(".option-btn")).to_have_count(2, timeout=5000)

        pax.vote_for("Yes")
        host.close_quiz()
        pcts = pax.get_percentages()
        assert pcts == [100, 0], f"Expected [100, 0], got {pcts}"

    def test_quiz_with_8_options(self, host: HostPage, pax: ParticipantPage):
        """Maximum option count: quiz with 8 options renders correctly."""
        options = ["Opt1", "Opt2", "Opt3", "Opt4", "Opt5", "Opt6", "Opt7", "Opt8"]
        host._page.click("#tab-quiz")
        host.create_quiz("Pick from many?", options)
        pax.join("EightOpt")
        expect(pax._page.locator(".option-btn")).to_have_count(8, timeout=5000)


# ---------------------------------------------------------------------------
# TestIdentityEdgeCases
# ---------------------------------------------------------------------------

class TestIdentityEdgeCases:

    def test_empty_name_ignored(self, pax: ParticipantPage):
        """Trying to rename to empty string should keep the current name."""
        pax.join("KeepMe")
        # Try to rename to empty
        pax._page.evaluate("_startNameEdit()")
        edit_input = pax._page.locator("#name-edit-input")
        expect(edit_input).to_be_visible(timeout=3000)
        edit_input.fill("")
        edit_input.press("Enter")

        pax._page.wait_for_timeout(500)
        name = pax._page.locator("#display-name").inner_text().strip()
        assert len(name) > 0, "Name should not be empty after attempting blank rename"

    def test_long_name_truncated_to_32(self, pax: ParticipantPage):
        """Names longer than 32 chars are truncated server-side."""
        pax.join("ShortFirst")
        long_name = "A" * 40

        pax._page.evaluate("_startNameEdit()")
        edit_input = pax._page.locator("#name-edit-input")
        expect(edit_input).to_be_visible(timeout=3000)
        edit_input.fill(long_name)
        edit_input.press("Enter")

        pax._page.wait_for_timeout(1000)
        # Read the name text span only — #display-name also holds an "edit" icon affordance.
        displayed = pax._page.locator("#display-name .display-name-text").inner_text().strip()
        assert len(displayed) <= 32, f"Name should be max 32 chars, got {len(displayed)}: '{displayed}'"

    def test_duplicate_name_admitted_and_flagged_on_own_card(self, server_url, playwright):
        """Duplicate names are permitted and flagged, never blocked.

        Per the participant-real-names spec, a taken name is a reported-but-allowed
        condition: both participants enter the session and both appear in the host
        list, and each client marks its OWN card with the duplicate indicator
        (computed from the UUID-free name broadcast: own name count >= 2). A
        unique, non-auto-assignable name is used so the assertion is robust
        against participants left over from earlier tests in the session-scoped
        server (the host list also shows offline participants).
        """
        dup_name = "DuplicateProbe"
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)
        b2, ctx2 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1 = ParticipantPage(ctx1.new_page())
        p2 = ParticipantPage(ctx2.new_page())

        host._page.goto(host_url())
        p1._page.goto(pax_url())
        p2._page.goto(pax_url())

        try:
            p1.join(dup_name)
            # The daemon accepts the collision (soft name_conflict flag, no 409),
            # so p2 keeps the name it asked for.
            p2.join(dup_name)

            # Both participants are admitted under the same name.
            expect(
                host._page.locator(f"#pax-list li .pax-name:has-text('{dup_name}')")
            ).to_have_count(2, timeout=5000)

            # Each client flags its own card from the name broadcast.
            for pax in (p1, p2):
                expect(pax._page.locator("#dup-indicator")).to_be_visible(timeout=5000)
                expect(pax._page.locator("#display-name")).to_have_class(
                    re.compile(r"\bis-duplicate\b"), timeout=5000
                )
        finally:
            for ctx in (ctx_host, ctx1, ctx2):
                ctx.close()
            for b in (b_host, b1, b2):
                b.close()

    def test_avatar_displayed_on_join(self, pax: ParticipantPage):
        """After joining, an avatar image is displayed."""
        pax.join("AvatarTest")
        avatar = pax._page.locator("#my-avatar")
        expect(avatar).to_be_visible(timeout=5000)
        src = avatar.get_attribute("src")
        assert src and len(src) > 0, f"Expected avatar image src, got: {src}"

    def test_avatar_persists_after_rename(self, pax: ParticipantPage):
        """Avatar should not change when participant renames."""
        pax.join("AvatarKeep")
        avatar = pax._page.locator("#my-avatar")
        expect(avatar).to_be_visible(timeout=5000)
        original_src = avatar.get_attribute("src")

        # Rename
        pax.rename("NewName")

        # Avatar should be the same
        pax._page.wait_for_timeout(500)
        new_src = avatar.get_attribute("src")
        assert new_src == original_src, f"Avatar changed after rename: {original_src} → {new_src}"
