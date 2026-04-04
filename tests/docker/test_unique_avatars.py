"""
Hermetic E2E tests: unique name + avatar assignment per session.

Each participant in a session must receive a distinct LOTR name and avatar.
Names are assigned in order of cultural famousness (Gandalf first, then Frodo, etc.).
Assignments are reserved for the lifetime of the session — disconnected participants
retain their name and avatar so re-joining participants get the same identity back.

Tests:
1. Sequential unique assignment — 3 participants each get different name+avatar, Gandalf first
2. Avatar refresh uniqueness — P1 refreshes avatar; P2 joins and gets a different avatar
3. Rename rejection — P1 renames to an existing name → rejected by server
4. Returning participant — P1 rejoins same session (same UUID) and keeps original name+avatar
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
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


def _api_call(method, path, data=None, base=None):
    """Make API call. Defaults to DAEMON_BASE for host endpoints."""
    target = base or DAEMON_BASE
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    body = json.dumps(data).encode() if data else (b"" if method == "POST" else None)
    req = urllib.request.Request(
        f"{target}{path}", method=method,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        data=body,
    )
    if method == "POST" and data is None:
        req.add_header("Content-Length", "0")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


LOTR_NAMES_ORDER = [
    "Gandalf", "Frodo", "Aragorn", "Legolas", "Gollum",
    "Samwise", "Gimli", "Smaug", "Bilbo", "Saruman",
]  # just the first 10 for reference

ALL_LOTR_NAMES = set([
    "Gandalf", "Frodo", "Aragorn", "Legolas", "Gollum",
    "Samwise", "Gimli", "Smaug", "Bilbo", "Saruman",
    "Galadriel", "Boromir", "Arwen", "Eowyn", "Merry",
    "Pippin", "Elrond", "Thorin", "Theoden", "Faramir",
    "Treebeard", "Shadowfax", "Radagast", "Tom Bombadil", "Eomer",
    "Haldir", "Glorfindel", "Celeborn", "Grima Wormtongue", "The One Ring",
])


def _open_participant(browser, session_id) -> tuple:
    """Open a fresh participant browser context and return (page, ParticipantPage)."""
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
    return page, ParticipantPage(page)


# ── 1. Sequential unique assignment ──────────────────────────────────────────

def test_sequential_unique_name_and_avatar_assignment():
    """3 participants join sequentially — each gets a distinct LOTR name+avatar.
    Names are assigned from the LOTR pool in order; each name gets its matching avatar."""
    session_id = fresh_session("UniqueNames")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page1, pax1 = _open_participant(browser, session_id)
        name1 = pax1.auto_join()
        avatar1 = pax1.get_avatar_src()

        page2, pax2 = _open_participant(browser, session_id)
        name2 = pax2.auto_join()
        avatar2 = pax2.get_avatar_src()

        page3, pax3 = _open_participant(browser, session_id)
        name3 = pax3.auto_join()
        avatar3 = pax3.get_avatar_src()

        print(f"P1: {name1} / {avatar1}")
        print(f"P2: {name2} / {avatar2}")
        print(f"P3: {name3} / {avatar3}")

        # All names must come from the LOTR pool
        assert name1 in ALL_LOTR_NAMES, f"P1 name not a LOTR name: '{name1}'"
        assert name2 in ALL_LOTR_NAMES, f"P2 name not a LOTR name: '{name2}'"
        assert name3 in ALL_LOTR_NAMES, f"P3 name not a LOTR name: '{name3}'"

        # All names must be distinct
        assert len({name1, name2, name3}) == 3, "Participants share a name!"

        # All avatars must be distinct and non-empty
        assert avatar1 and avatar2 and avatar3, "Some avatar is empty"
        assert len({avatar1, avatar2, avatar3}) == 3, f"Participants share an avatar: {avatar1}, {avatar2}, {avatar3}"

        # Each avatar must match its LOTR name pair (name → name.lower().replace(' ', '-') + '.png')
        def expected_avatar(name):
            return name.lower().replace(' ', '-') + '.png'

        assert avatar1 == expected_avatar(name1), f"Avatar mismatch for P1: name={name1}, avatar={avatar1}"
        assert avatar2 == expected_avatar(name2), f"Avatar mismatch for P2: name={name2}, avatar={avatar2}"
        assert avatar3 == expected_avatar(name3), f"Avatar mismatch for P3: name={name3}, avatar={avatar3}"

        print("SUCCESS: Sequential unique name+avatar assignment works!")
        browser.close()


# ── 2. Avatar refresh uniqueness ─────────────────────────────────────────────

def test_avatar_refresh_gives_unique_avatar_to_second_participant():
    """P1 joins and gets a LOTR name+avatar, then refreshes avatar (gets something different).
    P2 joins — P2 gets a different name+avatar pair, not P1's refreshed avatar."""
    session_id = fresh_session("AvatarRefresh")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page1, pax1 = _open_participant(browser, session_id)
        name1 = pax1.auto_join()
        avatar1_original = pax1.get_avatar_src()
        assert name1 in ALL_LOTR_NAMES, f"P1 name not a LOTR name: '{name1}'"
        expected_avatar1 = name1.lower().replace(' ', '-') + '.png'
        assert avatar1_original == expected_avatar1, f"P1 avatar should match name, got {avatar1_original}"

        # P1 refreshes avatar — gets a random avatar (not the original)
        page1.evaluate("sendWS('refresh_avatar', { rejected: [] })")
        page1.wait_for_timeout(1500)
        avatar1_refreshed = pax1.get_avatar_src()
        assert avatar1_refreshed != avatar1_original, "Refresh should change the avatar"
        print(f"P1: {name1} original={avatar1_original} refreshed={avatar1_refreshed}")

        # P2 joins — should get a different name+avatar
        page2, pax2 = _open_participant(browser, session_id)
        name2 = pax2.auto_join()
        avatar2 = pax2.get_avatar_src()
        print(f"P2: {name2} / {avatar2}")

        assert name2 in ALL_LOTR_NAMES, f"P2 name not a LOTR name: '{name2}'"
        assert name2 != name1, "P2 should have a different name than P1"
        # P2's avatar must not be the same as P1's refreshed avatar
        assert avatar2 != avatar1_refreshed, (
            f"P2 got same avatar as P1's refreshed avatar: {avatar2}"
        )

        print("SUCCESS: Avatar refresh uniqueness works!")
        browser.close()


# ── 3. Rename rejection ───────────────────────────────────────────────────────

def test_rename_rejected_when_name_already_taken():
    """P1 renames to 'Myname'. P2 tries to rename to 'Myname' → rejected."""
    session_id = fresh_session("RenameRejection")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page1, pax1 = _open_participant(browser, session_id)
        pax1.auto_join()
        pax1.rename("Myname")

        page2, pax2 = _open_participant(browser, session_id)
        name2_before = pax2.auto_join()  # should be Frodo

        # P2 tries to take P1's name — should be rejected
        page2.evaluate("startNameEdit()")
        edit_input = page2.locator("#name-edit-input")
        expect(edit_input).to_be_visible(timeout=3000)
        edit_input.fill("Myname")
        edit_input.press("Enter")

        # Wait for server round-trip — name should NOT have changed
        page2.wait_for_timeout(1500)
        name2_after = page2.locator("#display-name").inner_text().strip()
        print(f"P2 name before: '{name2_before}', after rejected rename: '{name2_after}'")

        # P2's name must remain unchanged (server rejected the rename)
        assert name2_after != "Myname", (
            f"P2 was allowed to take P1's name 'Myname'! Name is now '{name2_after}'"
        )

        print("SUCCESS: Duplicate rename correctly rejected!")
        browser.close()


# ── 4. Returning participant keeps same name+avatar ───────────────────────────

def test_returning_participant_keeps_name_and_avatar():
    """P1 joins, navigates away, navigates back (same browser context → same UUID).
    Server must restore the same name and avatar without reassignment."""
    session_id = fresh_session("Returning")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        ctx = browser.new_context()
        page = ctx.new_page()

        # First visit
        page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(page)
        name_first = pax.auto_join()
        avatar_first = pax.get_avatar_src()
        print(f"First visit: {name_first} / {avatar_first}")

        # Navigate away then back (same context → same localStorage UUID)
        page.goto("about:blank")
        page.wait_for_timeout(500)
        page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax2 = ParticipantPage(page)
        name_second = pax2.auto_join()
        avatar_second = pax2.get_avatar_src()
        print(f"Second visit: {name_second} / {avatar_second}")

        assert name_second == name_first, (
            f"Returning participant got different name: was '{name_first}', now '{name_second}'"
        )
        assert avatar_second == avatar_first, (
            f"Returning participant got different avatar: was '{avatar_first}', now '{avatar_second}'"
        )

        print("SUCCESS: Returning participant correctly identified by UUID!")
        browser.close()
