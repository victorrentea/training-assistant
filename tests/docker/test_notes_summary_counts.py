"""
Hermetic E2E tests: notes/summary nav items in the participant sidebar.

The participant UI shows Notes and Summary as sidebar nav items (data-nav="notes"
/ data-nav="summary") that are hidden until the corresponding file exists. Each nav
carries a relative-time badge (#notes-badge / #summary-badge) and a red unread alert
(.badge-alert) that clears once the participant opens the view.

Tests:
1. Nav items hidden on page load when the files are absent.
2. Dropping a notes file shows the nav live (WS notes_updated) with a relative-time
   badge and an unread alert — no page reload.
3. Same for the summary file.
4. Opening each view clears its unread alert.
5. After a reload, the nav items stay visible (state-driven) and the unread alert
   stays cleared.
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
from pages.participant_page import ParticipantPage
from playwright.sync_api import expect, sync_playwright
from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
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
            return data.get("daemon_session_folder")
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


def _is_relative_time(text: str) -> bool:
    """A freshly written file renders as 'just now' (or 'Nm/Nh/Nd ago')."""
    text = (text or "").strip()
    return text == "just now" or text.endswith("ago")


def _has_alert(badge) -> bool:
    return "badge-alert" in (badge.get_attribute("class") or "")


@pytest.mark.nightly
def test_notes_summary_nav_display_and_unread_alert():
    """
    Verifies:
    - Notes/Summary nav items hidden when files are absent on page load.
    - Dropping each file reveals its nav live (WS-driven) with a relative-time badge
      and an unread alert, without a reload.
    - Opening each view clears its unread alert.
    - After reload the navs stay visible (state-driven) with the alert still cleared.
    """
    session_id = fresh_session("NotesSummary")

    session_name = _await_condition(
        lambda: _get_active_session_name(session_id),
        timeout_ms=5000,
        msg="Could not get active session name from daemon",
    )

    # Ensure no notes/summary files exist at start.
    _remove_notes(session_name)
    _remove_summary(session_name)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(page)
        pax.join("NavTester")
        page.wait_for_timeout(500)

        notes_nav = page.locator('[data-nav="notes"]')
        summary_nav = page.locator('[data-nav="summary"]')
        notes_badge = page.locator("#notes-badge")
        summary_badge = page.locator("#summary-badge")

        # ── Step 1: no files — nav items hidden ──
        expect(notes_nav).to_be_hidden(timeout=3000)
        expect(summary_nav).to_be_hidden(timeout=3000)
        print("Step 1 OK: notes/summary nav items hidden when files absent")

        # ── Step 2: write notes — nav appears live (WS) with badge + unread alert ──
        _write_notes(session_name, 13)
        expect(notes_nav).to_be_visible(timeout=8000)
        notes_text = notes_badge.inner_text().strip()
        assert _is_relative_time(notes_text), (
            f"Notes badge should show relative time, got: {notes_text!r}"
        )
        assert _has_alert(notes_badge), "Notes badge should have unread alert after WS update"
        print(f"Step 2 OK: notes nav live, badge={notes_text!r}, unread alert present")

        # ── Step 3: write summary — nav appears live with badge + unread alert ──
        _write_summary(session_name, 17)
        expect(summary_nav).to_be_visible(timeout=8000)
        summary_text = summary_badge.inner_text().strip()
        assert _is_relative_time(summary_text), (
            f"Summary badge should show relative time, got: {summary_text!r}"
        )
        assert _has_alert(summary_badge), "Summary badge should have unread alert after WS update"
        print(f"Step 3 OK: summary nav live, badge={summary_text!r}, unread alert present")

        # ── Step 4: opening each view clears its unread alert ──
        notes_nav.click()
        _await_condition(
            lambda: not _has_alert(notes_badge),
            timeout_ms=3000,
            msg="Notes unread alert did not clear after opening the notes view",
        )
        summary_nav.click()
        _await_condition(
            lambda: not _has_alert(summary_badge),
            timeout_ms=3000,
            msg="Summary unread alert did not clear after opening the summary view",
        )
        print("Step 4 OK: opening each view cleared its unread alert")

        # ── Step 5: reload — navs persist from /state, alert stays cleared ──
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1000)
        expect(notes_nav).to_be_visible(timeout=5000)
        expect(summary_nav).to_be_visible(timeout=5000)
        assert _is_relative_time(notes_badge.inner_text().strip()), (
            "After reload, notes badge should show relative time from /state"
        )
        assert _is_relative_time(summary_badge.inner_text().strip()), (
            "After reload, summary badge should show relative time from /state"
        )
        assert not _has_alert(notes_badge), "Notes alert should stay cleared after reload"
        assert not _has_alert(summary_badge), "Summary alert should stay cleared after reload"
        print("Step 5 OK: reload keeps navs visible (state-driven) with alert cleared")

        browser.close()

    print("SUCCESS: notes/summary nav display and unread alert test passed!")
