"""
E2E tests for Connection/Reconnection, Poll edge cases, and Identity edge cases.

Run:
    pytest test_e2e_connection_poll_identity.py -v
"""

import re
import pytest
from playwright.sync_api import expect

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage
from conftest import api, host_browser_ctx, pax_browser_ctx


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
        pax._page.locator("#display-name").click()
        edit_input = pax._page.locator("#name-edit-input")
        expect(edit_input).to_be_visible(timeout=3000)
        edit_input.fill("Bob")
        edit_input.press("Enter")
        expect(pax._page.locator("#display-name")).to_have_text("Bob", timeout=3000)

        # Host should see "Bob" instead of "Alice"
        expect(host._page.locator("#pax-list")).to_contain_text("Bob", timeout=5000)

    @pytest.mark.usefixtures("clean_scores", "clean_qa")
    def test_participant_refresh_preserves_score(self, server_url, playwright):
        """Earn score via Q&A, refresh page, score is preserved after rejoin."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b_pax, ctx_pax = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        pax_page = ctx_pax.new_page()
        pax_page.goto("/")
        pax = ParticipantPage(pax_page)

        try:
            host._page.goto("/host")
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
        page1.goto("/host")
        # First host is connected — badge has class "connected"
        expect(page1.locator("#ws-badge.connected")).to_be_visible(timeout=5000)

        try:
            # Open second host tab
            page2 = ctx2.new_page()
            page2.goto("/host")
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
            page1.goto(server_url)
            pax = ParticipantPage(page1)
            pax.join("ReconTest")

            # Close the page
            page1.close()

            # Open new page in same context (same localStorage)
            page2 = ctx.new_page()
            page2.goto(server_url)

            # Should auto-join with saved name
            expect(page2.locator("#main-screen")).to_be_visible(timeout=10000)
            expect(page2.locator("#display-name")).to_have_text("ReconTest", timeout=5000)
        finally:
            ctx.close()
            b.close()


# ---------------------------------------------------------------------------
# TestPollEdgeCases
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def clean_poll(server_url):
    """Clear poll state before and after each test."""
    api(server_url, "put", "/api/poll/status", json={"open": False})
    api(server_url, "delete", "/api/poll")
    yield
    api(server_url, "put", "/api/poll/status", json={"open": False})
    api(server_url, "delete", "/api/poll")


@pytest.mark.usefixtures("clean_poll")
class TestPollEdgeCases:

    def test_vote_is_final_cannot_change(self, host: HostPage, pax: ParticipantPage):
        """After voting, clicking another option should not change the vote."""
        pax.join("VoteFinal")
        host._page.click("#tab-poll")
        host.create_poll("Pick one?", ["Alpha", "Beta", "Gamma"])
        pax.vote_for("Alpha")

        # Try clicking Beta - should not change vote
        pax._page.locator(".option-btn:has-text('Beta')").click()
        pax._page.wait_for_timeout(500)

        # Host should still show only 1 vote total
        expect(host._page.locator("text=1 total vote")).to_be_visible(timeout=3000)

    def test_multiple_participants_vote_correct_counts(self, server_url, playwright):
        """3 participants: P1→A, P2→B, P3→A. Host sees A=2, B=1."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)
        b2, ctx2 = pax_browser_ctx(server_url, playwright)
        b3, ctx3 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1 = ParticipantPage(ctx1.new_page())
        p2 = ParticipantPage(ctx2.new_page())
        p3 = ParticipantPage(ctx3.new_page())

        host._page.goto("/host")
        p1._page.goto("/")
        p2._page.goto("/")
        p3._page.goto("/")

        try:
            p1.join("Voter1")
            p2.join("Voter2")
            p3.join("Voter3")
            host.create_poll("Best letter?", ["A", "B", "C"])

            p1.vote_for("A")
            p2.vote_for("B")
            p3.vote_for("A")

            expect(host._page.locator("text=3 total vote")).to_be_visible(timeout=5000)

            host.close_poll()
            # Check percentages from any participant
            pcts = p1.get_percentages()
            # A=2/3≈67%, B=1/3≈33%, C=0%
            assert pcts[0] >= 60, f"Option A should be ~67%, got {pcts[0]}%"
            assert pcts[1] >= 30, f"Option B should be ~33%, got {pcts[1]}%"
            assert pcts[2] == 0, f"Option C should be 0%, got {pcts[2]}%"
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

        host._page.goto("/host")
        p1._page.goto("/")
        p2._page.goto("/")

        try:
            p1.join("FastVoter")
            p2.join("SlowVoter")
            host.create_poll("Speed test?", ["Right", "Wrong"])

            # P1 votes immediately
            p1.vote_for("Right")
            # Wait 2 seconds then P2 votes
            p2._page.wait_for_timeout(2000)
            p2.vote_for("Right")

            host.close_poll()
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

    def test_poll_with_2_options(self, host: HostPage, pax: ParticipantPage):
        """Minimum option count: poll with exactly 2 options works."""
        pax.join("TwoOpt")
        host._page.click("#tab-poll")
        host.create_poll("Yes or no?", ["Yes", "No"])
        expect(pax._page.locator(".option-btn")).to_have_count(2, timeout=5000)

        pax.vote_for("Yes")
        host.close_poll()
        pcts = pax.get_percentages()
        assert pcts == [100, 0], f"Expected [100, 0], got {pcts}"

    def test_poll_with_8_options(self, host: HostPage, pax: ParticipantPage):
        """Maximum option count: poll with 8 options renders correctly."""
        options = ["Opt1", "Opt2", "Opt3", "Opt4", "Opt5", "Opt6", "Opt7", "Opt8"]
        host._page.click("#tab-poll")
        host.create_poll("Pick from many?", options)
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
        pax._page.locator("#display-name").click()
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

        pax._page.locator("#display-name").click()
        edit_input = pax._page.locator("#name-edit-input")
        expect(edit_input).to_be_visible(timeout=3000)
        edit_input.fill(long_name)
        edit_input.press("Enter")

        pax._page.wait_for_timeout(1000)
        displayed = pax._page.locator("#display-name").inner_text().strip()
        assert len(displayed) <= 32, f"Name should be max 32 chars, got {len(displayed)}: '{displayed}'"

    def test_duplicate_names_both_in_host_list(self, server_url, playwright):
        """Two participants with the same name both appear in the host list."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)
        b2, ctx2 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1 = ParticipantPage(ctx1.new_page())
        p2 = ParticipantPage(ctx2.new_page())

        host._page.goto("/host")
        p1._page.goto("/")
        p2._page.goto("/")

        try:
            p1.join("Frodo")
            p2.join("Frodo")

            host._page.wait_for_timeout(1000)
            # Count "Frodo" occurrences in participant list
            frodo_count = host._page.locator("#pax-list li .pax-name:has-text('Frodo')").count()
            assert frodo_count == 2, f"Expected 2 entries for 'Frodo', got {frodo_count}"
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
        pax._page.locator("#display-name").click()
        edit_input = pax._page.locator("#name-edit-input")
        expect(edit_input).to_be_visible(timeout=3000)
        edit_input.fill("NewName")
        edit_input.press("Enter")
        expect(pax._page.locator("#display-name")).to_have_text("NewName", timeout=3000)

        # Avatar should be the same
        pax._page.wait_for_timeout(500)
        new_src = avatar.get_attribute("src")
        assert new_src == original_src, f"Avatar changed after rename: {original_src} → {new_src}"
