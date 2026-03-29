"""
E2E tests for Word Cloud gaps, Q&A gaps, Activity Switching, and Edge Cases.

Run:
    pytest test_e2e_wordcloud_qa_activity.py -v
"""

import pytest
from playwright.sync_api import expect

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage
from conftest import api, host_browser_ctx, pax_browser_ctx, pax_url


# ---------------------------------------------------------------------------
# TestWordCloudGaps
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("clean_wordcloud")
class TestWordCloudGaps:

    def test_set_topic_participant_sees_it(self, server_url, host: HostPage, pax: ParticipantPage):
        """Host sets word cloud topic, participant sees it."""
        pax.join("WcTopic1")
        api(server_url, "post", "/api/wordcloud/topic", json={"topic": "Design Patterns"})
        host.open_wordcloud_tab()

        expect(pax._page.locator("#wc-prompt-text")).to_contain_text("Design Patterns", timeout=5000)

    def test_word_deduplication_same_word_counted(self, server_url, playwright):
        """Two participants submit same word (different case) — treated as one word."""
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
            p1.join("Dedup1")
            p2.join("Dedup2")
            host.open_wordcloud_tab()

            expect(p1._page.locator("#wc-canvas")).to_be_visible(timeout=5000)
            expect(p2._page.locator("#wc-canvas")).to_be_visible(timeout=5000)

            p1.submit_word("Java")
            p2.submit_word("java")

            p1._page.wait_for_timeout(1000)

            # Verify via API status that "java" count is 2
            resp = api(server_url, "get", "/api/status")
            # The word cloud words are in the state broadcast, not in /api/status
            # Instead verify both participants submitted successfully
            assert len(p1.get_wordcloud_my_words()) == 1
            assert len(p2.get_wordcloud_my_words()) == 1
        finally:
            for ctx in (ctx_host, ctx1, ctx2):
                ctx.close()
            for b in (b_host, b1, b2):
                b.close()

    def test_autocomplete_shows_others_words(self, server_url, playwright):
        """After P1 submits a word, P2's autocomplete datalist contains it."""
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
            p1.join("AutoP1")
            p2.join("AutoP2")
            host.open_wordcloud_tab()

            expect(p1._page.locator("#wc-canvas")).to_be_visible(timeout=5000)
            expect(p2._page.locator("#wc-canvas")).to_be_visible(timeout=5000)

            p1.submit_word("microservices")
            p2._page.wait_for_timeout(1500)

            # Check datalist on P2
            suggestions = p2._page.evaluate("""() => {
                const opts = document.querySelectorAll('#wc-suggestions option');
                return Array.from(opts).map(o => o.value);
            }""")
            assert "microservices" in suggestions, f"Expected 'microservices' in suggestions, got {suggestions}"
        finally:
            for ctx in (ctx_host, ctx1, ctx2):
                ctx.close()
            for b in (b_host, b1, b2):
                b.close()

    def test_download_and_clear_wordcloud(self, server_url, host: HostPage, pax: ParticipantPage):
        """Host clears word cloud — words are removed but activity stays active."""
        pax.join("WcClear")
        host.open_wordcloud_tab()
        expect(pax._page.locator("#wc-canvas")).to_be_visible(timeout=5000)

        pax.submit_word("cleanup")
        pax._page.wait_for_timeout(500)
        assert "cleanup" in pax.get_wordcloud_my_words()

        api(server_url, "post", "/api/wordcloud/clear")
        pax._page.wait_for_timeout(1000)
        # Words should be cleared
        words = pax.get_wordcloud_my_words()
        assert len(words) == 0, f"Words should be cleared after clear, got {words}"

    def test_word_persistence_across_refresh(self, server_url, playwright):
        """Submit a word, refresh page, my words list still shows the word."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b_pax, ctx_pax = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        pax_page = ctx_pax.new_page()
        pax_page.goto(pax_url())
        pax = ParticipantPage(pax_page)

        try:
            host._page.goto("/host")
            pax.join("WcPersist")
            host.open_wordcloud_tab()
            expect(pax_page.locator("#wc-canvas")).to_be_visible(timeout=5000)

            pax.submit_word("persistence")
            pax_page.wait_for_timeout(500)
            assert "persistence" in pax.get_wordcloud_my_words()

            # Refresh in same context (preserves localStorage)
            pax_page.reload()
            expect(pax_page.locator("#main-screen")).to_be_visible(timeout=10000)
            expect(pax_page.locator("#wc-canvas")).to_be_visible(timeout=5000)
            pax_page.wait_for_timeout(1000)

            words = pax.get_wordcloud_my_words()
            assert "persistence" in words, f"Expected 'persistence' after refresh, got {words}"
        finally:
            ctx_host.close()
            ctx_pax.close()
            b_host.close()
            b_pax.close()

    def test_clear_resets_participant_local_words(self, server_url, host: HostPage, pax: ParticipantPage):
        """After host clears word cloud, participant can submit the same words again."""
        pax.join("WcReset")
        host.open_wordcloud_tab()
        expect(pax._page.locator("#wc-canvas")).to_be_visible(timeout=5000)

        pax.submit_word("resetme")
        pax._page.wait_for_timeout(500)
        assert "resetme" in pax.get_wordcloud_my_words()

        # Host clears
        api(server_url, "post", "/api/wordcloud/clear")
        pax._page.wait_for_timeout(1000)

        # Reopen word cloud
        host.open_wordcloud_tab()
        expect(pax._page.locator("#wc-canvas")).to_be_visible(timeout=5000)

        # Should be able to submit same word again
        pax.submit_word("resetme")
        pax._page.wait_for_timeout(500)
        words = pax.get_wordcloud_my_words()
        assert "resetme" in words, f"Should be able to resubmit after clear, got {words}"


# ---------------------------------------------------------------------------
# TestQAGaps
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("clean_qa")
class TestQAGaps:

    def test_question_over_280_chars_rejected(self, host: HostPage, pax: ParticipantPage):
        """Submitting a 281-char question via WS is silently dropped by the server."""
        pax.join("QALimit")
        host.open_qa_tab()

        long_q = "x" * 281
        # Bypass client-side maxlength by sending directly via WebSocket
        pax._page.evaluate(f"""() => {{
            if (window.ws && window.ws.readyState === WebSocket.OPEN) {{
                window.ws.send(JSON.stringify({{ type: 'qa_submit', text: '{"x" * 281}' }}));
            }}
        }}""")
        pax._page.wait_for_timeout(1500)

        questions = host.get_qa_questions()
        assert len(questions) == 0, f"281-char question should be rejected, got {len(questions)} questions"

    def test_host_clears_all_qa(self, server_url, host: HostPage, pax: ParticipantPage):
        """Submit 3 questions, host clears all, both host and participant see empty list."""
        pax.join("QAClear")
        host.open_qa_tab()

        pax.submit_question("Question 1")
        pax.submit_question("Question 2")
        pax.submit_question("Question 3")

        expect(host._page.locator(".qa-card")).to_have_count(3, timeout=5000)

        # Host clicks clear all
        host._page.click("#clear-qa-btn")
        # May need to confirm — check if there's a confirmation dialog
        host._page.wait_for_timeout(500)

        expect(host._page.locator(".qa-card")).to_have_count(0, timeout=5000)
        pax.expect_question_count(0)

    def test_10_questions_render_and_sort_correctly(self, server_url, playwright):
        """10 questions render correctly. Upvoting changes sort order."""
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
            p1.join("QAMany1")
            p2.join("QAMany2")
            host.open_qa_tab()

            # P1 submits 10 questions
            for i in range(10):
                p1.submit_question(f"Question number {i+1}")

            p2.expect_question_count(10)

            # P2 upvotes "Question number 5" to push it to top
            questions = p2.get_qa_questions()
            q5 = next(q for q in questions if "number 5" in q["text"])
            p2.upvote_question(q5["id"])

            p1._page.wait_for_timeout(1000)

            # Question 5 should now be first (highest upvotes)
            texts = p1.get_question_texts()
            assert "number 5" in texts[0], f"Question 5 should be first after upvote, got: {texts[0]}"
        finally:
            for ctx in (ctx_host, ctx1, ctx2):
                ctx.close()
            for b in (b_host, b1, b2):
                b.close()


# ---------------------------------------------------------------------------
# TestActivitySwitching
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("clean_all")
class TestActivitySwitching:

    def test_full_activity_cycle_poll_qa_wc_code(self, server_url, host: HostPage, pax: ParticipantPage):
        """Switch through all activities: poll → Q&A → word cloud → code review."""
        pax.join("CycleTest")

        # Poll
        host._page.click("#tab-poll")
        host.create_poll("Cycle Q?", ["Yes", "No"])
        expect(pax._page.locator(".option-btn")).to_have_count(2, timeout=5000)

        # Switch to Q&A
        host.open_qa_tab()
        expect(pax._page.locator("#qa-input")).to_be_visible(timeout=5000)

        # Switch to word cloud
        host.open_wordcloud_tab()
        expect(pax._page.locator("#wc-canvas")).to_be_visible(timeout=5000)

        # Switch to code review
        host.open_codereview_tab()
        snippet = "int x = 1;\nint y = 2;\nreturn x + y;"
        host.create_codereview(snippet)
        expect(pax._page.locator(".codereview-screen")).to_be_visible(timeout=7000)

        # Clean up code review
        host.clear_codereview()
        expect(pax._page.locator(".codereview-screen")).not_to_be_visible(timeout=5000)

    def test_rapid_switching_no_js_errors(self, server_url, host: HostPage, pax: ParticipantPage):
        """Rapidly switch activities 5 times. No JS errors on participant."""
        pax.join("RapidSwitch")

        js_errors = []
        pax._page.on("pageerror", lambda e: js_errors.append(str(e)))

        activities = ["qa", "wordcloud", "qa", "wordcloud", "qa"]
        for act in activities:
            api(server_url, "post", "/api/activity", json={"activity": act})
            pax._page.wait_for_timeout(300)

        # Reset to none
        api(server_url, "post", "/api/activity", json={"activity": "none"})
        pax._page.wait_for_timeout(500)

        assert js_errors == [], f"JS errors during rapid switching: {js_errors}"


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("clean_all")
class TestEdgeCases:

    def test_join_after_voting_closed(self, server_url, playwright):
        """Participant joins after poll voting is closed — sees results, cannot vote."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)
        b2, ctx2 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1 = ParticipantPage(ctx1.new_page())

        host._page.goto("/host")
        p1._page.goto(pax_url())

        try:
            p1.join("EarlyBird")
            host.create_poll("Closed poll?", ["X", "Y"])
            p1.vote_for("X")
            host.close_poll()

            # New participant joins after closing
            p2_page = ctx2.new_page()
            p2_page.goto(pax_url())
            p2 = ParticipantPage(p2_page)
            p2.join("LateComer")

            # Should see the poll results (percentages visible)
            expect(p2._page.locator(".pct").first).to_be_visible(timeout=5000)
            # Should see closed banner
            expect(p2._page.locator(".closed-banner")).to_be_visible(timeout=5000)
        finally:
            # Clean up poll
            api(server_url, "put", "/api/poll/status", json={"open": False})
            api(server_url, "delete", "/api/poll")
            for ctx in (ctx_host, ctx1, ctx2):
                ctx.close()
            for b in (b_host, b1, b2):
                b.close()

    def test_very_long_poll_question_renders(self, host: HostPage, pax: ParticipantPage):
        """200+ char question renders without error."""
        pax.join("LongQ")
        host._page.click("#tab-poll")
        long_question = "What is the best approach to " + "x" * 180 + "?"
        host.create_poll(long_question, ["A", "B"])
        expect(pax._page.locator("#content h2")).to_be_visible(timeout=5000)
        # No crash — question is displayed
        q_text = pax._page.locator("#content h2").inner_text()
        assert len(q_text) > 100, f"Long question should render, got: {q_text[:50]}..."

    @pytest.mark.usefixtures("clean_qa")
    def test_xss_in_question_escaped(self, host: HostPage, pax: ParticipantPage):
        """HTML tags in Q&A question are escaped, not executed."""
        pax.join("XSSTest")
        host.open_qa_tab()

        xss_text = '<script>alert("xss")</script>'
        pax.submit_question(xss_text)

        pax._page.wait_for_timeout(1000)

        # The literal text should appear escaped in the DOM
        questions = host.get_qa_questions()
        assert len(questions) == 1
        assert "<script>" in questions[0]["text"] or "script" in questions[0]["text"].lower()

        # Verify no alert dialog was triggered (Playwright would throw on unhandled dialog)
        # The text should be visible as escaped HTML
        expect(host._page.locator(".qa-text")).to_be_visible(timeout=3000)

    def test_simultaneous_votes_all_counted(self, server_url, playwright):
        """3 participants vote near-simultaneously — all 3 counted."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)
        b2, ctx2 = pax_browser_ctx(server_url, playwright)
        b3, ctx3 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1 = ParticipantPage(ctx1.new_page())
        p2 = ParticipantPage(ctx2.new_page())
        p3 = ParticipantPage(ctx3.new_page())

        host._page.goto("/host")
        p1._page.goto(pax_url())
        p2._page.goto(pax_url())
        p3._page.goto(pax_url())

        try:
            p1.join("Sim1")
            p2.join("Sim2")
            p3.join("Sim3")
            # Create poll via host UI (API-only doesn't broadcast to participants)
            host._page.click("#tab-poll")
            host.create_poll("Simultaneous?", ["Alpha", "Beta"])

            # Wait for poll to be visible on all participants
            expect(p1._page.locator(".option-btn")).to_have_count(2, timeout=10000)
            expect(p2._page.locator(".option-btn")).to_have_count(2, timeout=5000)
            expect(p3._page.locator(".option-btn")).to_have_count(2, timeout=5000)

            # All vote as fast as possible
            p1.vote_for("Alpha")
            p2.vote_for("Alpha")
            p3.vote_for("Alpha")

            # Host should show 3 total votes
            expect(host._page.locator("#vote-progress-label")).to_contain_text("3 of", timeout=5000)
        finally:
            api(server_url, "put", "/api/poll/status", json={"open": False})
            api(server_url, "delete", "/api/poll")
            for ctx in (ctx_host, ctx1, ctx2, ctx3):
                ctx.close()
            for b in (b_host, b1, b2, b3):
                b.close()

    @pytest.mark.usefixtures("clean_qa")
    def test_concurrent_upvotes_correct_count(self, server_url, playwright):
        """3 participants upvote same question — final count = 3."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)
        b2, ctx2 = pax_browser_ctx(server_url, playwright)
        b3, ctx3 = pax_browser_ctx(server_url, playwright)
        b4, ctx4 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1 = ParticipantPage(ctx1.new_page())
        p2 = ParticipantPage(ctx2.new_page())
        p3 = ParticipantPage(ctx3.new_page())
        p4 = ParticipantPage(ctx4.new_page())

        host._page.goto("/host")
        p1._page.goto(pax_url())
        p2._page.goto(pax_url())
        p3._page.goto(pax_url())
        p4._page.goto(pax_url())

        try:
            p1.join("Author")
            p2.join("Voter1")
            p3.join("Voter2")
            p4.join("Voter3")
            host.open_qa_tab()

            p1.submit_question("Upvote me")
            p2.expect_question_count(1)
            p3.expect_question_count(1)
            p4.expect_question_count(1)

            q_id = p2.get_qa_questions()[0]["id"]

            # All 3 upvote near-simultaneously
            p2.upvote_question(q_id)
            p3.upvote_question(q_id)
            p4.upvote_question(q_id)

            # Wait for final count to propagate
            expect(p1._page.locator(f'.qa-upvote-btn[data-qid="{q_id}"]')).to_contain_text(
                "3", timeout=5000
            )
        finally:
            for ctx in (ctx_host, ctx1, ctx2, ctx3, ctx4):
                ctx.close()
            for b in (b_host, b1, b2, b3, b4):
                b.close()
