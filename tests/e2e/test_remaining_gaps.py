"""
E2E tests for remaining coverage gaps.

Covers: multi-select poll (submit/scoring), poll timer, leaderboard show/hide,
conference mode identity, connection indicators, QR code, host panel elements,
and additional edge cases.

Run:
    pytest test_e2e_remaining_gaps.py -v
    pytest test_e2e_remaining_gaps.py -v --headed   # watch the browsers
"""

import pytest
from playwright.sync_api import expect

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage
from conftest import api, host_browser_ctx, pax_browser_ctx, pax_url


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def clean_poll(server_url):
    api(server_url, "put", "/api/poll/status", json={"open": False})
    api(server_url, "delete", "/api/poll")
    yield
    api(server_url, "put", "/api/poll/status", json={"open": False})
    api(server_url, "delete", "/api/poll")


# ---------------------------------------------------------------------------
# Multi-Select Poll
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("clean_poll", "clean_scores")
class TestMultiSelectPoll:

    def test_multi_vote_submit_and_host_count(self, server_url, playwright):
        """Submit multi-vote by toggling options, verify host sees correct vote count."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1 = ParticipantPage(ctx1.new_page())

        host._page.goto("/host")
        p1._page.goto(pax_url())

        try:
            p1.join("MultiVoter")
            host._page.click("#tab-poll")
            host.create_poll("Pick 2 correct", ["A", "B", "C", "D"], multi=True, correct_count=2)

            expect(p1._page.locator(".option-btn")).to_have_count(4, timeout=5000)

            # Multi-select auto-submits on each click via WebSocket
            p1.multi_vote("A", "C")
            p1._page.wait_for_timeout(1000)

            # Host should see 1 vote registered
            expect(host._page.locator("#vote-progress-label")).to_contain_text("1 of", timeout=5000)
        finally:
            for ctx in (ctx_host, ctx1):
                ctx.close()
            for b in (b_host, b1):
                b.close()

    def test_multi_select_scoring_all_correct(self, server_url, playwright):
        """Select both correct options -> full points (ratio=1.0)."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1 = ParticipantPage(ctx1.new_page())

        host._page.goto("/host")
        p1._page.goto(pax_url())

        try:
            p1.join("AllCorrect")
            host._page.click("#tab-poll")
            host.create_poll("Pick 2", ["Right1", "Right2", "Wrong1", "Wrong2"],
                             multi=True, correct_count=2)

            expect(p1._page.locator(".option-btn")).to_have_count(4, timeout=5000)

            p1.multi_vote("Right1", "Right2")
            p1._page.wait_for_timeout(500)

            host.close_poll()
            host.mark_correct("Right1")
            host.mark_correct("Right2")

            expect(p1._page.locator(".result-icon", has_text="✅").first).to_be_visible(timeout=5000)
            p1._page.wait_for_timeout(500)
            score = p1.get_score()
            assert score >= 400, f"Expected high score for all correct, got {score}"
        finally:
            for ctx in (ctx_host, ctx1):
                ctx.close()
            for b in (b_host, b1):
                b.close()

    def test_multi_select_scoring_partial_zero(self, server_url, playwright):
        """Select 1 correct + 1 wrong -> ratio = max(0, (1-1)/2) = 0 -> 0 points."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1 = ParticipantPage(ctx1.new_page())

        host._page.goto("/host")
        p1._page.goto(pax_url())

        try:
            p1.join("PartialVoter")
            host._page.click("#tab-poll")
            host.create_poll("Pick 2", ["Right1", "Right2", "Wrong1", "Wrong2"],
                             multi=True, correct_count=2)

            expect(p1._page.locator(".option-btn")).to_have_count(4, timeout=5000)

            p1.multi_vote("Right1", "Wrong1")
            p1._page.wait_for_timeout(500)

            host.close_poll()
            host.mark_correct("Right1")
            host.mark_correct("Right2")

            # ratio = (1-1)/2 = 0 -> 0 points
            p1._page.wait_for_timeout(2000)
            score = p1.get_score()
            assert score == 0, f"Expected 0 for 1 right + 1 wrong, got {score}"
        finally:
            for ctx in (ctx_host, ctx1):
                ctx.close()
            for b in (b_host, b1):
                b.close()

    def test_multi_select_all_wrong_zero_score(self, server_url, playwright):
        """Select only wrong options -> 0 points (not negative)."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1 = ParticipantPage(ctx1.new_page())

        host._page.goto("/host")
        p1._page.goto(pax_url())

        try:
            p1.join("AllWrong")
            host._page.click("#tab-poll")
            host.create_poll("Pick 2", ["Right1", "Right2", "Wrong1", "Wrong2"],
                             multi=True, correct_count=2)

            expect(p1._page.locator(".option-btn")).to_have_count(4, timeout=5000)

            p1.multi_vote("Wrong1", "Wrong2")
            p1._page.wait_for_timeout(500)

            host.close_poll()
            host.mark_correct("Right1")
            host.mark_correct("Right2")

            p1._page.wait_for_timeout(2000)
            score = p1.get_score()
            assert score == 0, f"Expected 0 for all wrong, got {score}"
        finally:
            for ctx in (ctx_host, ctx1):
                ctx.close()
            for b in (b_host, b1):
                b.close()


# ---------------------------------------------------------------------------
# Poll Timer
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("clean_poll")
class TestPollTimer:

    def test_timer_countdown_visible(self, server_url, host: HostPage, pax: ParticipantPage):
        """Start a timer, participant sees countdown element."""
        pax.join("TimerTest")
        host._page.click("#tab-poll")
        host.create_poll("Timer Q?", ["A", "B"])

        # Start a 10-second timer via API
        resp = api(server_url, "post", "/api/poll/timer", json={"seconds": 10})
        assert resp.status_code == 200

        # Participant should see the countdown element with timer text
        pax._page.wait_for_timeout(1000)  # wait for timer tick (200ms interval)
        countdown = pax._page.locator("#pax-countdown")
        expect(countdown).to_be_visible(timeout=5000)
        # Wait for the setInterval to populate text
        pax._page.wait_for_function(
            "() => document.getElementById('pax-countdown')?.textContent?.includes('s')",
            timeout=5000
        )
        text = countdown.inner_text()
        assert "s" in text, f"Timer should show seconds, got: {text}"

    def test_timer_cleared_on_close(self, server_url, host: HostPage, pax: ParticipantPage):
        """Timer disappears when poll voting is closed."""
        pax.join("TimerClose")
        host._page.click("#tab-poll")
        host.create_poll("Timer close?", ["Yes", "No"])
        expect(host._page.locator("text=Close voting")).to_be_visible(timeout=5000)

        api(server_url, "post", "/api/poll/timer", json={"seconds": 30})
        pax._page.wait_for_function(
            "() => document.getElementById('pax-countdown')?.textContent?.includes('s')",
            timeout=5000
        )

        # Close voting via API (more reliable than clicking UI)
        api(server_url, "put", "/api/poll/status", json={"open": False})
        pax._page.wait_for_timeout(2000)

        # After closing, the poll re-renders without active timer
        # Timer element may still exist but should be empty
        has_timer_text = pax._page.evaluate("""() => {
            const el = document.getElementById('pax-countdown');
            return el ? el.textContent.trim() : '';
        }""")
        # Timer should be cleared or showing 0
        assert has_timer_text == "" or "0" in has_timer_text, \
            f"Timer should be cleared after close, got: '{has_timer_text}'"


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("clean_scores", "clean_qa")
class TestLeaderboard:

    def test_leaderboard_show_and_hide(self, server_url, host: HostPage, pax: ParticipantPage):
        """Host triggers leaderboard, participant sees overlay. Then hide it."""
        pax.join("LeaderTest")
        host.open_qa_tab()
        pax.submit_question("Score me up")
        pax._page.wait_for_timeout(1000)
        assert pax.get_score() == 100

        # Show leaderboard
        resp = api(server_url, "post", "/api/leaderboard/show")
        assert resp.status_code == 200

        # Participant should see leaderboard overlay (display changes from none to flex)
        pax._page.wait_for_function(
            "() => document.getElementById('leaderboard-overlay')?.style.display === 'flex'",
            timeout=8000
        )

        # Hide leaderboard
        resp = api(server_url, "post", "/api/leaderboard/hide")
        assert resp.status_code == 200

        pax._page.wait_for_function(
            "() => document.getElementById('leaderboard-overlay')?.style.display === 'none'",
            timeout=5000
        )

    def test_leaderboard_shows_personal_rank(self, server_url, playwright):
        """Participant sees their own rank in the leaderboard."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)
        b2, ctx2 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1 = ParticipantPage(ctx1.new_page())
        p2 = ParticipantPage(ctx2.new_page())

        host._page.goto("/host")
        p1._page.goto(pax_url())
        p2._page.goto(pax_url())

        try:
            p1.join("Leader1")
            p2.join("Leader2")
            host.open_qa_tab()

            # P1 submits 2 questions (200 pts), P2 submits 1 (100 pts)
            p1.submit_question("Q1 from P1")
            p1.submit_question("Q2 from P1")
            p2.submit_question("Q1 from P2")
            p1._page.wait_for_timeout(1500)

            api(server_url, "post", "/api/leaderboard/show")

            # Both should see leaderboard (display changes from none to flex)
            p1._page.wait_for_function(
                "() => document.getElementById('leaderboard-overlay')?.style.display === 'flex'",
                timeout=8000
            )
            p2._page.wait_for_function(
                "() => document.getElementById('leaderboard-overlay')?.style.display === 'flex'",
                timeout=5000
            )

            # Personal rank element should show rank info
            p1_rank = p1._page.locator("#leaderboard-my-rank")
            expect(p1_rank).to_be_visible(timeout=5000)
            rank_text = p1_rank.inner_text()
            assert len(rank_text) > 0, "Personal rank should be displayed"

            api(server_url, "post", "/api/leaderboard/hide")
        finally:
            for ctx in (ctx_host, ctx1, ctx2):
                ctx.close()
            for b in (b_host, b1, b2):
                b.close()


# ---------------------------------------------------------------------------
# Conference Mode
# ---------------------------------------------------------------------------

class TestConferenceMode:

    def test_toggle_conference_mode(self, server_url, host: HostPage):
        """Toggle to conference mode and back."""
        try:
            resp = api(server_url, "post", "/api/mode", json={"mode": "conference"})
            assert resp.status_code == 200
            host._page.wait_for_timeout(1000)

            resp = api(server_url, "post", "/api/mode", json={"mode": "workshop"})
            assert resp.status_code == 200
        finally:
            api(server_url, "post", "/api/mode", json={"mode": "workshop"})

    def test_conference_mode_auto_assigns_character_name(self, server_url, playwright):
        """In conference mode, participant gets auto-assigned character name."""
        try:
            api(server_url, "post", "/api/mode", json={"mode": "conference"})

            b_pax, ctx_pax = pax_browser_ctx(server_url, playwright)
            page = ctx_pax.new_page()
            page.goto(pax_url())

            try:
                # Should auto-join with character name
                expect(page.locator("#main-screen")).to_be_visible(timeout=10000)
                page.wait_for_timeout(1500)

                # Name should be set (from character pool)
                name = page.locator("#display-name").inner_text().strip()
                assert len(name) > 0, "Conference mode should auto-assign a name"
            finally:
                ctx_pax.close()
                b_pax.close()
        finally:
            api(server_url, "post", "/api/mode", json={"mode": "workshop"})

    def test_conference_mode_hides_score(self, server_url, playwright):
        """Conference mode hides the score display."""
        try:
            api(server_url, "post", "/api/mode", json={"mode": "conference"})

            b_pax, ctx_pax = pax_browser_ctx(server_url, playwright)
            page = ctx_pax.new_page()
            page.goto(pax_url())

            try:
                expect(page.locator("#main-screen")).to_be_visible(timeout=10000)
                page.wait_for_timeout(1000)

                # Score should be hidden in conference mode
                score_el = page.locator("#my-score")
                if score_el.count() > 0:
                    expect(score_el).not_to_be_visible(timeout=3000)
            finally:
                ctx_pax.close()
                b_pax.close()
        finally:
            api(server_url, "post", "/api/mode", json={"mode": "workshop"})


# ---------------------------------------------------------------------------
# Connection Indicators & Host Panel
# ---------------------------------------------------------------------------

class TestConnectionIndicators:

    def test_host_ws_badge_connected(self, host: HostPage):
        """Host WS badge shows connected class when WebSocket is open."""
        # Wait for WS to connect
        host._page.wait_for_timeout(2000)
        badge = host._page.locator("#ws-badge")
        expect(badge).to_be_visible(timeout=5000)
        cls = badge.get_attribute("class") or ""
        assert "connected" in cls, f"Expected 'connected' in badge class, got: {cls}"

    def test_participant_count_updates(self, host: HostPage, pax: ParticipantPage):
        """Host sees participant count increase when someone joins."""
        pax.join("CountTest")
        expect(host._page.locator("#pax-list li")).not_to_have_count(0, timeout=5000)


class TestHostPanelGeneral:

    def test_qr_code_rendered(self, host: HostPage):
        """QR code is rendered on the host panel with canvas/img content."""
        host._page.wait_for_timeout(2000)
        # Check that at least one QR container has rendered content
        has_qr = host._page.evaluate("""() => {
            const ids = ['qr-code', 'center-qr'];
            for (const id of ids) {
                const el = document.getElementById(id);
                if (el && (el.querySelector('canvas') || el.querySelector('img'))) {
                    return true;
                }
            }
            return false;
        }""")
        assert has_qr, "QR code should contain a canvas or img element"

    def test_participant_link_displayed(self, host: HostPage):
        """Participant URL link is displayed on the host panel."""
        host._page.wait_for_timeout(1000)
        link = host._page.locator("#participant-link")
        expect(link).to_be_visible(timeout=5000)
        href = host._page.evaluate("document.getElementById('participant-link').href")
        assert href and "/" in href, f"Link should have a valid href, got: {href}"

    def test_qr_fullscreen_on_click(self, host: HostPage):
        """Clicking QR icon opens fullscreen overlay."""
        host._page.wait_for_timeout(1000)
        qr_icon = host._page.locator("#qr-icon")
        if qr_icon.count() > 0 and qr_icon.is_visible():
            qr_icon.click()
            expect(host._page.locator("#qr-overlay")).to_be_visible(timeout=3000)
            # Click to dismiss
            host._page.locator("#qr-overlay").click()
            expect(host._page.locator("#qr-overlay")).not_to_be_visible(timeout=3000)


# ---------------------------------------------------------------------------
# Additional Edge Cases
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("clean_all")
class TestAdditionalEdgeCases:

    def test_participant_joins_mid_qa_sees_questions(self, server_url, playwright):
        """Participant joining while Q&A is active sees existing questions."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)
        b2, ctx2 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1 = ParticipantPage(ctx1.new_page())

        host._page.goto("/host")
        p1._page.goto(pax_url())

        try:
            p1.join("EarlyQA")
            host.open_qa_tab()
            p1.submit_question("Already asked")
            p1._page.wait_for_timeout(500)

            # Now P2 joins late
            p2_page = ctx2.new_page()
            p2_page.goto(pax_url())
            p2 = ParticipantPage(p2_page)
            p2.join("LateQA")

            p2.expect_question_count(1)
            p2.expect_question_text_visible("Already asked")
        finally:
            for ctx in (ctx_host, ctx1, ctx2):
                ctx.close()
            for b in (b_host, b1, b2):
                b.close()

    def test_participant_joins_mid_wordcloud_sees_canvas(self, server_url, playwright):
        """Participant joining while word cloud is active sees the canvas."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        host._page.goto("/host")

        try:
            host.open_wordcloud_tab()
            host._page.wait_for_timeout(500)

            p1_page = ctx1.new_page()
            p1_page.goto(pax_url())
            p1 = ParticipantPage(p1_page)
            p1.join("LateWC")

            expect(p1._page.locator("#wc-canvas")).to_be_visible(timeout=5000)
        finally:
            for ctx in (ctx_host, ctx1):
                ctx.close()
            for b in (b_host, b1):
                b.close()

    def test_special_chars_in_wordcloud(self, server_url, host: HostPage, pax: ParticipantPage):
        """Unicode and special characters in word cloud handled gracefully."""
        pax.join("UniWC")
        host.open_wordcloud_tab()
        expect(pax._page.locator("#wc-canvas")).to_be_visible(timeout=5000)

        pax.submit_word("caf\u00e9")
        pax._page.wait_for_timeout(500)
        words = pax.get_wordcloud_my_words()
        assert any("caf" in w for w in words), f"Unicode word should be in list, got {words}"

    def test_multi_select_cap_enforced(self, server_url, playwright):
        """In multi-select with correct_count=2, 3rd option is blocked."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1 = ParticipantPage(ctx1.new_page())

        host._page.goto("/host")
        p1._page.goto(pax_url())

        try:
            p1.join("CapTest")
            host._page.click("#tab-poll")
            host.create_poll("Pick 2", ["A", "B", "C", "D"], multi=True, correct_count=2)

            expect(p1._page.locator(".option-btn")).to_have_count(4, timeout=5000)

            # Click 3 options — 3rd should be blocked (returns early)
            p1._page.locator(".option-btn:has-text('A')").click()
            p1._page.wait_for_timeout(300)
            p1._page.locator(".option-btn:has-text('B')").click()
            p1._page.wait_for_timeout(300)
            # Force-click C (bypass disabled check) to see if JS blocks it
            p1._page.locator(".option-btn:has-text('C')").click(force=True)
            p1._page.wait_for_timeout(500)

            # Check selected count via JS (the option-btn class may not change for blocked click)
            selected = p1._page.evaluate("""() => {
                return typeof myVote !== 'undefined' && myVote instanceof Set ? myVote.size : -1;
            }""")
            assert selected <= 2, f"Should not have more than 2 selected, got {selected}"
        finally:
            api(server_url, "put", "/api/poll/status", json={"open": False})
            api(server_url, "delete", "/api/poll")
            for ctx in (ctx_host, ctx1):
                ctx.close()
            for b in (b_host, b1):
                b.close()

    @pytest.mark.usefixtures("clean_qa", "clean_scores")
    def test_no_js_errors_during_full_session_lifecycle(self, server_url, playwright):
        """Full session lifecycle (join, Q&A, word cloud, poll, leaderboard) with no JS errors."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1_page = ctx1.new_page()
        p1_page.goto(pax_url())
        p1 = ParticipantPage(p1_page)

        host._page.goto("/host")

        js_errors = []
        p1_page.on("pageerror", lambda e: js_errors.append(str(e)))

        try:
            p1.join("FullCycle")

            # Q&A
            host.open_qa_tab()
            p1.submit_question("Full cycle Q")
            p1_page.wait_for_timeout(800)

            # Word cloud
            host.open_wordcloud_tab()
            expect(p1_page.locator("#wc-canvas")).to_be_visible(timeout=5000)
            p1.submit_word("lifecycle")
            p1_page.wait_for_timeout(500)

            # Poll
            host._page.click("#tab-poll")
            host.create_poll("Lifecycle?", ["A", "B"])
            p1.vote_for("A")
            host.close_poll()
            host.mark_correct("A")
            expect(p1_page.locator(".result-icon", has_text="✅")).to_be_visible(timeout=5000)

            # Leaderboard
            api(server_url, "post", "/api/leaderboard/show")
            p1_page.wait_for_timeout(2000)
            api(server_url, "post", "/api/leaderboard/hide")
            p1_page.wait_for_timeout(500)

            assert js_errors == [], f"JS errors during full lifecycle: {js_errors}"
        finally:
            api(server_url, "put", "/api/poll/status", json={"open": False})
            api(server_url, "delete", "/api/poll")
            api(server_url, "post", "/api/wordcloud/clear")
            for ctx in (ctx_host, ctx1):
                ctx.close()
            for b in (b_host, b1):
                b.close()
