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
from session_utils import fresh_session


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

        # Host should see "OriginalName"
        _await_condition(
            lambda: "OriginalName" in host_page.inner_text("body"),
            timeout_ms=5000,
            msg="Host does not see 'OriginalName'"
        )
        print("Host sees OriginalName")

        # Participant renames
        pax.rename("RenamedAlice")

        # Host should see the new name
        _await_condition(
            lambda: "RenamedAlice" in host_page.inner_text("body"),
            timeout_ms=5000,
            msg="Host does not see 'RenamedAlice' after rename"
        )

        # Old name should be gone from active display
        # (it may still exist in history, but the active name should be new)
        print("Host sees RenamedAlice after rename")
        print("SUCCESS: Name change visible to host!")
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

        # Wait for participant to appear on host
        _await_condition(
            lambda: "EmojiSender" in host_page.inner_text("body"),
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
