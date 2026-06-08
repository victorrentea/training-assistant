"""
Hermetic E2E test: emoji master switch (host footer ❤️ badge).

The host can silence all participant emoji reactions for the session with one
click. This test drives the real backend + daemon + two browser contexts and
proves the end-to-end behaviour:

  switch OFF -> participant emoji is silently dropped (no float on host)
  switch ON  -> participant emoji floats on the host again

Companion to test_participant_interactions.py::test_emoji_reaction_visible_to_host
(which proves the default-ON path) — same two-browser shape, runs in the same
default hermetic suite.
"""

import os
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

from playwright.sync_api import sync_playwright, expect

from pages.participant_page import ParticipantPage
from session_utils import fresh_session, daemon_has_participant


BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


def _await_condition(fn, timeout_ms=10000, poll_ms=300, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def _await_badge_state(host_page, expected, timeout_ms=5000):
    """Wait until the emoji master badge carries the expected class token."""
    badge = host_page.locator("#emoji-master-badge")
    _await_condition(
        lambda: expected in (badge.get_attribute("class") or ""),
        timeout_ms=timeout_ms,
        msg=f"emoji-master-badge never became '{expected}'",
    )


def _assert_stays_zero(host_page, hold_ms=2500, poll_ms=200):
    """Fail fast if any host emoji float appears within the hold window.

    The emoji round-trip (participant POST -> daemon -> host WS -> showHostEmoji)
    is sub-second in-container, so a float that is going to appear appears well
    inside this window. A clean window is strong evidence the daemon dropped it.
    """
    deadline = time.monotonic() + hold_ms / 1000
    while time.monotonic() < deadline:
        count = host_page.locator(".host-emoji-float").count()
        assert count == 0, f"Expected no host emoji float while switch is OFF, saw {count}"
        time.sleep(poll_ms / 1000)


def test_emoji_master_switch_blocks_and_restores():
    """Host toggles the master switch → participant emoji is dropped, then restored."""
    session_id = fresh_session("EmojiMasterSwitch")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ── Host
        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-quiz")).to_be_visible(timeout=10000)
        # Badge starts enabled (default).
        _await_badge_state(host_page, "connected")

        # ── Participant
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("EmojiSender")
        _await_condition(
            lambda: daemon_has_participant(session_id, "EmojiSender"),
            timeout_ms=5000,
            msg="Host does not see 'EmojiSender'",
        )
        emoji_btn = pax_page.locator("#emoji-main-bar button").first
        emoji_btn.wait_for(state="visible", timeout=5000)

        # ── Phase 1: switch OFF → emoji dropped (start here so the DOM is clean)
        host_page.locator("#emoji-master-badge").click()
        _await_badge_state(host_page, "disabled")  # class flips only after the toggle POST returns
        emoji_btn.click(force=True)  # force: the button animates on hover (scale-110), never "stable"
        _assert_stays_zero(host_page, hold_ms=2500)
        print("Phase 1 OK: emoji dropped while master switch OFF")

        # ── Phase 2: switch back ON → emoji floats again
        host_page.locator("#emoji-master-badge").click()
        _await_badge_state(host_page, "connected")
        emoji_btn.click(force=True)
        _await_condition(
            lambda: host_page.locator(".host-emoji-float").count() > 0,
            timeout_ms=5000,
            msg="Emoji did not reappear after re-enabling master switch",
        )
        print("Phase 2 OK: emoji floats again after master switch ON")

        browser.close()
