"""
Hermetic E2E test: participant name correctly shown in host UI.

Regression for: participant name shown as 'Guest <uuid[:8]>' in host UI immediately
after joining, because Railway's state.participant_names was empty when participant
connected WS (daemon assigns names via REST, not via Railway).

Fix: daemon sends 'participant_registered' WS message to Railway on registration
so Railway has the real name before the participant opens WS.
"""

import os
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from playwright.sync_api import sync_playwright, expect

from pages.participant_page import ParticipantPage
from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:8081")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


@pytest.mark.nightly
def test_participant_name_shown_in_host_ui():
    """Participant joins → host UI shows real daemon-assigned name (not 'Guest ...').

    This tests the full pipeline:
    1. Daemon registers participant and assigns a LOTR name
    2. Daemon syncs name to Railway via WS (participant_registered message)
    3. Daemon sends participant_list_updated directly to host browser
    4. Host browser receives broadcast and renders participant list
    5. Name shown must be the real name, not the 'Guest <uuid[:8]>' fallback
    """
    session_id = fresh_session("NameDisplayTest")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Open host panel
        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10000)

        # Participant navigates to session and auto-joins (daemon assigns LOTR name)
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        assigned_name = pax.auto_join()
        print(f"Daemon assigned participant name: {assigned_name!r}")

        # Wait for host UI to show participant count = 1 (confirms WS broadcast arrived)
        expect(host_page.locator("#pax-count")).to_have_text("1", timeout=8000)

        # The name shown must be the real assigned name, not a 'Guest ...' fallback
        name_text = host_page.locator("#pax-list .pax-name-text").first.inner_text().strip()
        assert "Guest " not in name_text, (
            f"Host shows guest fallback '{name_text}' instead of real name '{assigned_name}'"
        )
        assert assigned_name in name_text or name_text in assigned_name, (
            f"Host shows '{name_text}', expected name containing '{assigned_name}'"
        )

        print(f"SUCCESS: Host shows correct name '{name_text}' for participant '{assigned_name}'")
        browser.close()


@pytest.mark.nightly
def test_participant_count_correct_in_host_ui():
    """Two participants join → host UI shows count = 2 with both real names."""
    session_id = fresh_session("CountTest")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-poll")).to_be_visible(timeout=10000)

        # Two participants join
        pax1_ctx = browser.new_context()
        pax1_page = pax1_ctx.new_page()
        pax1_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax1 = ParticipantPage(pax1_page)
        name1 = pax1.auto_join()

        pax2_ctx = browser.new_context()
        pax2_page = pax2_ctx.new_page()
        pax2_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax2 = ParticipantPage(pax2_page)
        name2 = pax2.auto_join()

        print(f"Participants joined: {name1!r}, {name2!r}")

        # Host should show count = 2
        expect(host_page.locator("#pax-count")).to_have_text("2", timeout=8000)

        # Both names must be real (no 'Guest ...' entries)
        name_els = host_page.locator("#pax-list .pax-name-text").all()
        assert len(name_els) == 2, f"Expected 2 participants in list, got {len(name_els)}"
        names_shown = [el.inner_text().strip() for el in name_els]
        for name_shown in names_shown:
            assert "Guest " not in name_shown, (
                f"Host shows guest fallback '{name_shown}' instead of real name"
            )

        print(f"SUCCESS: Host shows count=2 with names: {names_shown}")
        browser.close()
