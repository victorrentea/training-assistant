"""
Hermetic E2E test: agenda .docx dropped into the session folder mid-session is
picked up live (without a daemon restart), exactly like notes/ai-summary.

Regression for: agenda only appeared after a daemon restart because the agenda
path was resolved once at startup/session-create and never re-probed in the loop.
"""

import base64
import json
import os
import sys
import urllib.request

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from pages.participant_page import ParticipantPage
from playwright.sync_api import expect, sync_playwright
from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
SESSIONS_FOLDER = os.environ.get("SESSIONS_FOLDER", "/tmp/test-sessions")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


def _get_active_session_name(session_id: str) -> str | None:
    """Return the active session folder name from daemon host state."""
    try:
        auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
        req = urllib.request.Request(
            f"{DAEMON_BASE}/api/{session_id}/host/state",
            headers={"Authorization": f"Basic {auth}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read()).get("daemon_session_folder")
    except Exception:
        return None


def _agenda_path(session_name: str) -> str:
    return os.path.join(SESSIONS_FOLDER, session_name, "agenda.docx")


def _write_agenda(session_name: str) -> None:
    """Write a minimal agenda .docx. The daemon only checks the .docx suffix to
    decide availability, so a placeholder file is enough to flip has_agenda."""
    folder = os.path.join(SESSIONS_FOLDER, session_name)
    os.makedirs(folder, exist_ok=True)
    with open(_agenda_path(session_name), "wb") as f:
        f.write(b"PK\x03\x04 placeholder agenda docx")


def _remove_agenda(session_name: str) -> None:
    try:
        os.remove(_agenda_path(session_name))
    except FileNotFoundError:
        pass


@pytest.mark.nightly
def test_agenda_appears_live_without_restart():
    session_id = fresh_session("AgendaLive")
    session_name = _get_active_session_name(session_id)
    assert session_name, "Could not resolve active session folder name"

    # Start with no agenda in the folder.
    _remove_agenda(session_name)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(page)
        pax.join("AgendaTester")
        page.wait_for_timeout(500)

        agenda_nav = page.locator('[data-nav="agenda"]')

        # ── Step 1: no agenda → nav hidden ──
        expect(agenda_nav).to_be_hidden(timeout=3000)
        print("Step 1 OK: agenda nav hidden when no agenda file present")

        # ── Step 2: drop agenda.docx mid-session → nav appears live via WS ──
        # No page reload: this is the regression — the daemon must re-probe the
        # folder and broadcast agenda_updated to the already-connected participant.
        _write_agenda(session_name)
        expect(agenda_nav).to_be_visible(timeout=8000)
        print("Step 2 OK: agenda nav appeared live after dropping agenda.docx (no restart)")

        # ── Step 3: remove agenda → nav hides live ──
        _remove_agenda(session_name)
        expect(agenda_nav).to_be_hidden(timeout=8000)
        print("Step 3 OK: agenda nav hid live after removing agenda.docx")

        browser.close()

    print("SUCCESS: agenda live pickup test passed!")
