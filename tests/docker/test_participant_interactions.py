"""
Hermetic E2E tests: participant interactions.

- Name change: participant renames → host sees new name
- Emoji reaction: participant sends emoji → host page shows it
"""

import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from playwright.sync_api import sync_playwright, expect

from pages.participant_page import ParticipantPage
from pages.host_page import HostPage
from session_utils import fresh_session, daemon_has_participant


BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:8081")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


def _await_condition(fn, timeout_ms=10000, poll_ms=300, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def test_participant_rename_visible_to_host():
    """Participant renames themselves → host participant list shows new name."""
    session_id = fresh_session("RenameTest")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Host
        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10000)

        # Participant joins with auto-name
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("OriginalName")

        expect(host_page.locator("#pax-list .pax-name-text", has_text="OriginalName")).to_be_visible(timeout=8000)

        # Participant renames
        pax.rename("RenamedAlice")

        expect(host_page.locator("#pax-list .pax-name-text", has_text="RenamedAlice")).to_be_visible(timeout=8000)
        expect(host_page.locator("#pax-list .pax-name-text", has_text="OriginalName")).to_have_count(0, timeout=8000)

        print("Host sees RenamedAlice after rename")
        print("SUCCESS: Name change visible to host!")
        browser.close()


def test_avatar_refresh_visible_to_participant_and_host():
    """Participant refreshes avatar → participant top avatar and host list avatar update live."""
    session_id = fresh_session("AvatarRefresh")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10000)

        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("AvatarUser")

        expect(host_page.locator("#pax-list .pax-name-text", has_text="AvatarUser")).to_be_visible(timeout=8000)

        def _host_avatar_src() -> str:
            return host_page.evaluate(
                """() => {
                    const rows = Array.from(document.querySelectorAll('#pax-list li'));
                    const row = rows.find((li) => {
                        const name = li.querySelector('.pax-name-text');
                        return name && name.textContent && name.textContent.trim() === 'AvatarUser';
                    });
                    if (!row) return '';
                    const img = row.querySelector('img.avatar');
                    return img ? (img.getAttribute('src') || '') : '';
                }"""
            )

        before_participant = pax.get_avatar_src()
        before_host = _host_avatar_src()

        # Trigger avatar refresh exactly like the participant UI
        pax_page.click("#my-avatar")
        expect(pax_page.locator("#avatar-modal .avatar-refresh-btn")).to_be_visible(timeout=3000)
        pax_page.click("#avatar-modal .avatar-refresh-btn")

        _await_condition(
            lambda: pax.get_avatar_src() and pax.get_avatar_src() != before_participant,
            timeout_ms=8000,
            msg="Participant avatar did not update after refresh",
        )
        after_participant = pax.get_avatar_src()

        _await_condition(
            lambda: (
                _host_avatar_src()
                and _host_avatar_src() != before_host
            ),
            timeout_ms=8000,
            msg="Host participant avatar did not update after participant refresh",
        )

        print(f"Participant avatar: {before_participant} -> {after_participant}")
        print("SUCCESS: Avatar refresh propagated to participant and host without reload!")
        browser.close()


def test_emoji_reaction_visible_to_host():
    """Participant sends emoji → host page shows the emoji."""
    session_id = fresh_session("EmojiTest")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Host
        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10000)

        # Participant joins
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("EmojiSender")

        # Wait for participant to register in daemon state
        _await_condition(
            lambda: daemon_has_participant(session_id, "EmojiSender"),
            timeout_ms=5000,
            msg="Host does not see 'EmojiSender'"
        )

        # Participant clicks an emoji — use the first emoji button (heart)
        emoji_btn = pax_page.locator("#emoji-center button, .emoji-btn").first
        emoji_btn.wait_for(state="visible", timeout=5000)
        emoji_btn.click()
        print("Participant clicked emoji")

        # Host should see a floating emoji (div.host-emoji-float created by showHostEmoji())
        _await_condition(
            lambda: host_page.locator(".host-emoji-float").count() > 0,
            timeout_ms=5000,
            msg="Host did not receive emoji reaction (no .host-emoji-float element)"
        )

        print("SUCCESS: Emoji reaction received by host!")
        browser.close()
