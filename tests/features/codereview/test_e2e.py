"""
End-to-end browser tests for the Code Review feature.

Tests cover the full lifecycle: creating a snippet, participant line selection,
host review phase, line confirmation with score awarding, and cleanup.

Run:
    pytest test_e2e_codereview.py -v
    pytest test_e2e_codereview.py -v --headed   # watch the browsers
"""

import pytest
import requests
from playwright.sync_api import expect

from pages.host_page import HostPage
from pages.participant_page import ParticipantPage
from conftest import api, host_browser_ctx, pax_browser_ctx, pax_url


JAVA_SNIPPET = """\
public List<String> getActiveUserEmails(List<User> users) {
    List<String> emails = new ArrayList<>();
    for (int i = 0; i <= users.size(); i++) {
        if (users.get(i).isActive()) {
            emails.add(users.get(i).getEmail());
        }
    }
    return emails;
}"""

# Line 3 contains the off-by-one bug: i <= users.size()
BUG_LINE = 3


@pytest.mark.usefixtures("clean_codereview")
class TestCodeReview:

    def test_start_code_review_participant_sees_snippet(
        self, host: HostPage, pax: ParticipantPage
    ):
        """Host creates a code review — participant's screen switches to the code view."""
        pax.join("Alice")
        host.open_codereview_tab()
        host.create_codereview(JAVA_SNIPPET)

        expect(pax._page.locator(".codereview-screen")).to_be_visible(timeout=7000)
        expect(pax._page.locator(".codereview-pline").first).to_be_visible(timeout=5000)
        expect(pax._page.locator(".codereview-pline")).to_have_count(9, timeout=5000)

    def test_select_and_deselect_lines(
        self, host: HostPage, pax: ParticipantPage
    ):
        """Participant can select a line and then deselect it by clicking again."""
        pax.join("Bob")
        host.open_codereview_tab()
        host.create_codereview(JAVA_SNIPPET)

        expect(pax._page.locator(".codereview-screen")).to_be_visible(timeout=7000)
        expect(pax._page.locator(".codereview-pline-clickable").first).to_be_visible(timeout=5000)

        pax.select_codereview_line(BUG_LINE)
        selections = pax.get_codereview_selections()
        assert BUG_LINE in selections, f"Line {BUG_LINE} should be selected, got {selections}"

        pax.deselect_codereview_line(BUG_LINE)
        selections = pax.get_codereview_selections()
        assert BUG_LINE not in selections, f"Line {BUG_LINE} should be deselected, got {selections}"
        assert len(selections) == 0

    def test_multiple_participants_select_lines(self, server_url, playwright):
        """Two participants select different lines; host sees counts for both."""
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
            p1.join("Charlie")
            p2.join("Diana")
            host.open_codereview_tab()
            host.create_codereview(JAVA_SNIPPET)

            expect(p1._page.locator(".codereview-screen")).to_be_visible(timeout=7000)
            expect(p2._page.locator(".codereview-screen")).to_be_visible(timeout=7000)
            expect(p1._page.locator(".codereview-pline-clickable").first).to_be_visible(timeout=5000)
            expect(p2._page.locator(".codereview-pline-clickable").first).to_be_visible(timeout=5000)

            p1.select_codereview_line(3)
            p2.select_codereview_line(4)

            host._page.wait_for_timeout(1500)

            counts = host.get_codereview_line_counts()
            assert len(counts) >= 1, f"Host should see at least 1 line with selections, got {counts}"
        finally:
            for ctx in (ctx_host, ctx1, ctx2):
                ctx.close()
            for b in (b_host, b1, b2):
                b.close()

    def test_end_selection_shows_review_phase(
        self, host: HostPage, pax: ParticipantPage
    ):
        """When host ends the selection phase, participant UI reflects the closed state."""
        pax.join("Eve")
        host.open_codereview_tab()
        host.create_codereview(JAVA_SNIPPET)

        expect(pax._page.locator(".codereview-screen")).to_be_visible(timeout=7000)
        expect(pax._page.locator(".codereview-pline-clickable").first).to_be_visible(timeout=5000)

        host.close_codereview_selection()

        expect(host._page.locator("#codereview-phase-label")).to_contain_text("Review", timeout=5000)

        pax._page.wait_for_timeout(1500)
        clickable_count = pax._page.locator(".codereview-pline-clickable").count()
        assert clickable_count == 0, f"Lines should not be clickable after selection ends, found {clickable_count}"

    def test_confirm_line_awards_200_points(
        self, host: HostPage, pax: ParticipantPage
    ):
        """Participant selects the correct line; host confirms it; participant earns 200 pts."""
        pax.join("Frank")
        host.open_codereview_tab()
        host.create_codereview(JAVA_SNIPPET)

        expect(pax._page.locator(".codereview-screen")).to_be_visible(timeout=7000)
        expect(pax._page.locator(".codereview-pline-clickable").first).to_be_visible(timeout=5000)

        pax.select_codereview_line(BUG_LINE)

        host.close_codereview_selection()
        host._page.wait_for_timeout(500)
        host.confirm_codereview_line(BUG_LINE)

        # Wait for score broadcast and animation to complete
        expect(pax._page.locator("#my-score")).to_be_visible(timeout=7000)
        pax._page.wait_for_timeout(1500)
        score = pax.get_score()
        assert 195 <= score <= 205, f"Expected ~200 after confirmed line, got {score}"

    def test_participant_names_in_review_panel(self, server_url, playwright):
        """After ending selection, clicking a line on the host panel shows participant names."""
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b1, ctx1 = pax_browser_ctx(server_url, playwright)

        host = HostPage(ctx_host.new_page())
        p1 = ParticipantPage(ctx1.new_page())

        host._page.goto("/host")
        p1._page.goto(pax_url())

        try:
            p1.join("Grace")
            host.open_codereview_tab()
            host.create_codereview(JAVA_SNIPPET)

            expect(p1._page.locator(".codereview-screen")).to_be_visible(timeout=7000)
            expect(p1._page.locator(".codereview-pline-clickable").first).to_be_visible(timeout=5000)

            p1.select_codereview_line(BUG_LINE)

            host.close_codereview_selection()
            host._page.evaluate(f"selectCodeReviewLine({BUG_LINE})")

            expect(host._page.locator("#codereview-side-panel")).to_be_visible(timeout=5000)
            expect(
                host._page.locator("#codereview-side-panel .codereview-participant-row")
            ).to_have_count(1, timeout=5000)
            expect(
                host._page.locator("#codereview-side-panel .codereview-participant-row").first
            ).to_contain_text("Grace", timeout=5000)
        finally:
            for ctx in (ctx_host, ctx1):
                ctx.close()
            for b in (b_host, b1):
                b.close()

    def test_snippet_validation_too_short_and_too_long(self, server_url):
        """API rejects empty snippets and snippets exceeding 50 lines."""
        resp_empty = api(server_url, "post", "/api/codereview", json={"snippet": ""})
        assert resp_empty.status_code == 400

        long_snippet = "\n".join(f"line {i}" for i in range(51))
        resp_long = api(server_url, "post", "/api/codereview", json={"snippet": long_snippet})
        assert resp_long.status_code == 400

        resp_valid = api(server_url, "post", "/api/codereview", json={"snippet": "int x = 1;"})
        assert resp_valid.status_code == 200

    def test_close_code_review_returns_to_idle(
        self, host: HostPage, pax: ParticipantPage
    ):
        """After host clears the code review, participant's codereview-screen disappears."""
        pax.join("Heidi")
        host.open_codereview_tab()
        host.create_codereview(JAVA_SNIPPET)

        expect(pax._page.locator(".codereview-screen")).to_be_visible(timeout=7000)

        host.clear_codereview()

        expect(pax._page.locator(".codereview-screen")).not_to_be_visible(timeout=7000)

    def test_syntax_highlighting_applied(
        self, host: HostPage, pax: ParticipantPage
    ):
        """Creating a CR with Java language causes highlight.js to add hljs span classes."""
        pax.join("Ivan")
        host.open_codereview_tab()
        host.create_codereview(JAVA_SNIPPET, language="Java")

        expect(pax._page.locator(".codereview-screen")).to_be_visible(timeout=7000)
        expect(pax._page.locator(".codereview-pcode").first).to_be_visible(timeout=5000)

        pax._page.wait_for_timeout(1000)
        has_hljs = pax._page.evaluate("""() => {
            const codes = document.querySelectorAll('.codereview-pcode');
            for (const el of codes) {
                if (el.querySelector('span[class*="hljs"]')) return true;
            }
            return false;
        }""")
        assert has_hljs, "Expected highlight.js to apply hljs-* span classes inside .codereview-pcode"

    def test_language_selection_propagates(
        self, host: HostPage, pax: ParticipantPage
    ):
        """Setting language to Java via dropdown is reflected in participant-side highlighting."""
        pax.join("Judy")
        host.open_codereview_tab()
        host.create_codereview(JAVA_SNIPPET, language="Java")

        expect(pax._page.locator(".codereview-screen")).to_be_visible(timeout=7000)
        expect(pax._page.locator(".codereview-pline")).to_have_count(9, timeout=5000)

        pax._page.wait_for_timeout(1000)

        highlighted_span_count = pax._page.evaluate("""() =>
            document.querySelectorAll('.codereview-pcode span[class*="hljs"]').length
        """)
        assert highlighted_span_count > 0, f"Expected Java syntax highlighting spans, found {highlighted_span_count}"
