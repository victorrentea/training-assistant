"""
E2E tests for session ID security.

Verifies:
- Landing page shows code entry form
- Valid session code redirects to participant page
- Invalid session code shows error / redirects back
- Participant can join and interact via session-scoped URLs
- Host panel displays session code
- Direct access without session code redirects to landing
"""
import requests
import pytest
from playwright.sync_api import expect

from conftest import (
    HOST_USER,
    HOST_PASS,
    api,
    host_browser_ctx,
    pax_browser_ctx,
    host_url,
)
from pages.participant_page import ParticipantPage
from pages.host_page import HostPage


class TestLandingPage:
    """Landing page at / shows session code entry."""

    def test_landing_page_renders(self, server_url, playwright):
        browser, ctx = pax_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        page.goto("/")
        expect(page.locator("#code-input")).to_be_visible(timeout=5000)
        expect(page.locator("#join-btn")).to_be_visible(timeout=3000)
        expect(page).to_have_title("Join Session - Interact", timeout=3000)
        ctx.close()
        browser.close()

    def test_session_active_endpoint(self, server_url):
        r = requests.get(f"{server_url}/api/session/active")
        assert r.status_code == 200
        assert r.json()["active"] is True

    def test_host_landing_does_not_render_active_session_card(self, server_url, playwright):
        browser, ctx = host_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        page.goto("/host")
        expect(page.locator(".landing-title")).to_have_text("Start Session", timeout=5000)
        expect(page.locator(".rejoin-card")).to_have_count(0, timeout=5000)
        ctx.close()
        browser.close()


class TestSessionJoin:
    """Joining via session code."""

    def test_valid_code_redirects_to_participant(self, server_url, session_id, playwright):
        browser, ctx = pax_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        page.goto("/")

        # Type session code and click Join
        page.fill("#code-input", session_id)
        page.click("#join-btn")

        # Should redirect to /{session_id}/
        page.wait_for_url(f"**/{session_id}/**", timeout=5000)
        expect(page.locator("#main-screen")).to_be_visible(timeout=10000)

        ctx.close()
        browser.close()

    def test_invalid_code_returns_404(self, server_url):
        # Direct HTTP request to invalid session returns 404
        r = requests.get(f"{server_url}/zzzzzz/")
        assert r.status_code == 404

    def test_direct_link_with_valid_code(self, server_url, session_id, playwright):
        browser, ctx = pax_browser_ctx(server_url, playwright)
        page = ctx.new_page()

        # Navigate directly to /{session_id}
        page.goto(f"/{session_id}")
        expect(page.locator("#main-screen")).to_be_visible(timeout=10000)

        ctx.close()
        browser.close()

    def test_case_insensitive_code(self, server_url, session_id, playwright):
        browser, ctx = pax_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        page.goto("/")

        # Type uppercase session code
        page.fill("#code-input", session_id.upper())
        page.click("#join-btn")

        # Should redirect successfully (code is lowercased by JS)
        page.wait_for_url(f"**/{session_id}/**", timeout=5000)
        expect(page.locator("#main-screen")).to_be_visible(timeout=10000)

        ctx.close()
        browser.close()


class TestSessionScopedAPIs:
    """Participant APIs only work under valid session prefix."""

    def test_suggest_name_with_valid_session(self, server_url, session_id):
        r = requests.get(f"{server_url}/{session_id}/api/suggest-name")
        assert r.status_code == 200
        data = r.json()
        assert "name" in data

    def test_suggest_name_with_invalid_session_404(self, server_url):
        r = requests.get(f"{server_url}/zzzzzz/api/suggest-name")
        assert r.status_code == 404

    def test_status_with_valid_session(self, server_url, session_id):
        r = requests.get(f"{server_url}/{session_id}/api/status")
        assert r.status_code == 200

    def test_status_with_invalid_session_404(self, server_url):
        r = requests.get(f"{server_url}/zzzzzz/api/status")
        assert r.status_code == 404


class TestHostSessionCode:
    """Host panel shows the session code."""

    def test_host_sees_session_code(self, server_url, session_id, playwright):
        browser, ctx = host_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        page.goto(host_url())

        # Wait for WebSocket state to arrive and session code bar to appear
        code_bar = page.locator("#session-code-bar")
        expect(code_bar).to_be_visible(timeout=10000)

        code_display = page.locator("#session-code-display")
        expect(code_display).to_have_text(session_id, timeout=5000)

        ctx.close()
        browser.close()

    def test_host_topbar_uses_participants_label(self, server_url, playwright):
        browser, ctx = host_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        page.goto(host_url())

        expect(page.locator(".host-top-pax .stat-label")).to_have_text("participants", timeout=5000)

        ctx.close()
        browser.close()

    def test_stop_button_never_disabled(self, server_url, playwright):
        browser, ctx = host_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        page.goto(host_url())

        stop_btn = page.locator("#stop-session-btn-left")
        expect(stop_btn).to_be_visible(timeout=10000)
        expect(stop_btn).to_be_enabled(timeout=10000)

        # Regression: remained enabled after async state render updates.
        page.wait_for_timeout(1500)
        expect(stop_btn).to_be_enabled(timeout=3000)

        ctx.close()
        browser.close()

    def test_footer_slides_badge_border_matches_other_footer_badges(self, server_url, playwright):
        browser, ctx = host_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        page.goto(host_url())

        styles = page.evaluate(
            """() => {
                const slides = document.getElementById('slides-catalog-icon');
                const git = document.getElementById('git-repos-badge');
                const s = getComputedStyle(slides);
                const g = getComputedStyle(git);
                return {
                    slidesBorder: s.borderTopColor,
                    gitBorder: g.borderTopColor,
                    slidesOpacity: s.opacity,
                    gitOpacity: g.opacity,
                };
            }"""
        )

        assert styles["slidesBorder"] == styles["gitBorder"]
        assert styles["slidesOpacity"] == styles["gitOpacity"]

        ctx.close()
        browser.close()

    def test_footer_badges_use_div_tooltips_not_title(self, server_url, playwright):
        browser, ctx = host_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        page.goto(host_url())
        page.wait_for_timeout(1200)

        state = page.evaluate(
            """() => {
                const ids = [
                    'ws-badge',
                    'daemon-badge',
                    'overlay-badge',
                    'notes-badge',
                    'summary-badge',
                    'btn-transcription-lang',
                    'token-cost',
                    'git-repos-badge',
                    'slides-log-badge',
                    'slides-catalog-icon',
                ];
                return ids.map((id) => {
                    const el = document.getElementById(id);
                    return {
                        id,
                        hasTitleAttr: !!el && el.hasAttribute('title'),
                        hasTooltipDiv: !!el && !!el.querySelector('.footer-badge-tooltip'),
                    };
                });
            }"""
        )

        assert all(not item["hasTitleAttr"] for item in state), state
        missing = [item["id"] for item in state if not item["hasTooltipDiv"]]
        assert not missing, missing

        ctx.close()
        browser.close()


class TestWebSocketSessionGating:
    """WebSocket connections are gated by session ID."""

    def test_ws_valid_session_connects(self, server_url, session_id, playwright):
        """Participant connects via /ws/{session_id}/{uuid} successfully."""
        browser, ctx = pax_browser_ctx(server_url, playwright)
        page = ctx.new_page()
        page.goto(f"/{session_id}")
        expect(page.locator("#main-screen")).to_be_visible(timeout=10000)

        # Verify participant name appears (auto-assigned), confirming WS connected
        expect(page.locator("#display-name")).not_to_be_empty(timeout=5000)

        ctx.close()
        browser.close()

    def test_ws_invalid_session_rejected(self, server_url):
        """WebSocket to /ws/badcode/{uuid} is rejected."""
        import websockets.sync.client as wsc
        ws_url = server_url.replace("http://", "ws://")
        try:
            ws = wsc.connect(f"{ws_url}/ws/zzzzzz/test-uuid", close_timeout=3)
            # If connection succeeds, it should close with 1008
            msg = ws.recv()  # might get close frame
            ws.close()
            # If we get here without error, the server accepted (shouldn't happen)
            pytest.fail("Expected WebSocket rejection for invalid session")
        except Exception:
            pass  # Expected — connection rejected or closed with 1008


class TestParticipantInteractionWithSession:
    """Full participant interaction flow through session-scoped URLs."""

    def test_participant_joins_and_is_visible_on_host(
        self, server_url, session_id, playwright
    ):
        b_host, ctx_host = host_browser_ctx(server_url, playwright)
        b_pax, ctx_pax = pax_browser_ctx(server_url, playwright)

        host_page = ctx_host.new_page()
        host_page.goto(host_url())
        host = HostPage(host_page)

        pax_page = ctx_pax.new_page()
        pax_page.goto(f"/{session_id}")
        pax = ParticipantPage(pax_page)
        pax.join("SessionTestUser")

        # Host should see the participant in the list
        expect(
            host_page.locator(".pax-name-text:has-text('SessionTestUser')")
        ).to_be_visible(timeout=10000)

        for c in (ctx_host, ctx_pax):
            c.close()
        for b in (b_host, b_pax):
            b.close()
