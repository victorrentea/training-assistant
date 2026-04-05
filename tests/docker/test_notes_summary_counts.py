"""
Hermetic E2E tests: notes/summary count display in participant bar.

Tests:
1. Buttons disabled on page load when counts are zero
2. Buttons enabled with correct count labels from /state (no flash)
3. notes_updated WS message updates label and triggers flash
4. summary_updated WS message updates label and triggers flash
"""

import base64
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from playwright.sync_api import sync_playwright, expect

from pages.participant_page import ParticipantPage
from session_utils import fresh_session


BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:8081")
SESSIONS_FOLDER = os.environ.get("SESSIONS_FOLDER", "/tmp/test-sessions")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


def _await_condition(fn, timeout_ms=8000, poll_ms=200, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def _get_active_session_name(session_id: str) -> str | None:
    """Return the active session folder name from daemon host state."""
    try:
        auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
        req = urllib.request.Request(
            f"{DAEMON_BASE}/api/{session_id}/host/state",
            headers={"Authorization": f"Basic {auth}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("session_name")
    except Exception:
        return None


def _write_notes(session_name: str, lines: int) -> None:
    """Write a notes .txt file with the given number of non-empty lines."""
    folder = os.path.join(SESSIONS_FOLDER, session_name)
    os.makedirs(folder, exist_ok=True)
    content = "\n".join(f"Note line {i+1}" for i in range(lines))
    with open(os.path.join(folder, "notes.txt"), "w") as f:
        f.write(content)


def _write_summary(session_name: str, points: int) -> None:
    """Write an ai-summary.md file with the given number of bullet points."""
    folder = os.path.join(SESSIONS_FOLDER, session_name)
    os.makedirs(folder, exist_ok=True)
    content = "\n".join(f"- Summary point {i+1}" for i in range(points))
    with open(os.path.join(folder, "ai-summary.md"), "w") as f:
        f.write(content)


def _remove_notes(session_name: str) -> None:
    notes_path = os.path.join(SESSIONS_FOLDER, session_name, "notes.txt")
    try:
        os.remove(notes_path)
    except FileNotFoundError:
        pass


def _remove_summary(session_name: str) -> None:
    summary_path = os.path.join(SESSIONS_FOLDER, session_name, "ai-summary.md")
    try:
        os.remove(summary_path)
    except FileNotFoundError:
        pass


@pytest.mark.nightly
def test_notes_summary_count_display_and_ws_flash():
    """
    Verifies:
    - Buttons disabled when counts are 0 on page load
    - Buttons enabled with correct count labels after state load with non-zero counts
    - Yellow flash CSS class applied when WS notes_updated/summary_updated message arrives
    """
    session_id = fresh_session("NotesCounts")

    # Get the session folder name
    session_name = _await_condition(
        lambda: _get_active_session_name(session_id),
        timeout_ms=5000,
        msg="Could not get active session name from daemon",
    )

    # Ensure no notes/summary files exist at start
    _remove_notes(session_name)
    _remove_summary(session_name)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ── Step 1: Load page with no counts — buttons should be disabled ──
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("CountTester")

        # Give WS a moment to stabilize
        pax_page.wait_for_timeout(500)

        notes_btn = pax_page.locator("#notes-btn")
        summary_btn = pax_page.locator("#summary-btn")
        expect(notes_btn).to_be_disabled(timeout=3000)
        expect(summary_btn).to_be_disabled(timeout=3000)
        print("Step 1 OK: both buttons disabled when counts are 0")

        # ── Step 2: Write files, wait for daemon to broadcast, check WS flash ──
        _write_notes(session_name, 13)
        _await_condition(
            lambda: not pax_page.locator("#notes-btn").is_disabled(),
            timeout_ms=6000,
            msg="Notes button did not become enabled after writing notes file",
        )
        notes_text = pax_page.locator("#notes-btn").inner_text()
        assert "13" in notes_text, f"Notes button label should contain '13', got: {notes_text!r}"

        notes_class = pax_page.locator("#notes-btn").get_attribute("class") or ""
        assert "count-flash" in notes_class, (
            f"Notes button should have count-flash CSS class after WS update, got: {notes_class!r}"
        )
        print(f"Step 2 OK: notes button enabled, label contains '13', flash class present")

        # ── Step 3: Write summary, wait for broadcast, check WS flash ──
        _write_summary(session_name, 17)
        _await_condition(
            lambda: not pax_page.locator("#summary-btn").is_disabled(),
            timeout_ms=6000,
            msg="Summary button did not become enabled after writing summary file",
        )
        summary_text = pax_page.locator("#summary-btn").inner_text()
        assert "17" in summary_text, f"Summary button label should contain '17', got: {summary_text!r}"

        summary_class = pax_page.locator("#summary-btn").get_attribute("class") or ""
        assert "count-flash" in summary_class, (
            f"Summary button should have count-flash CSS class after WS update, got: {summary_class!r}"
        )
        print("Step 3 OK: summary button enabled, label contains '17', flash class present")

        # ── Step 4: Reload page — counts should come from /state, no flash ──
        # Update files to different counts before reload
        _write_notes(session_name, 20)
        _write_summary(session_name, 5)
        # Wait for daemon to pick up the changes
        time.sleep(1.5)

        pax_page.reload(wait_until="networkidle")
        pax_page.wait_for_timeout(1000)

        notes_text_after = pax_page.locator("#notes-btn").inner_text()
        summary_text_after = pax_page.locator("#summary-btn").inner_text()

        assert "20" in notes_text_after, (
            f"After reload, notes button should show 20, got: {notes_text_after!r}"
        )
        assert "5" in summary_text_after, (
            f"After reload, summary button should show 5, got: {summary_text_after!r}"
        )

        notes_class_after = pax_page.locator("#notes-btn").get_attribute("class") or ""
        summary_class_after = pax_page.locator("#summary-btn").get_attribute("class") or ""
        assert "count-flash" not in notes_class_after, (
            f"Notes button should NOT flash on page load (state-driven), got: {notes_class_after!r}"
        )
        assert "count-flash" not in summary_class_after, (
            f"Summary button should NOT flash on page load (state-driven), got: {summary_class_after!r}"
        )
        print("Step 4 OK: reload shows updated counts without flash")

        browser.close()

    print("SUCCESS: Notes/summary count display and WS flash test passed!")
