"""
Hermetic E2E: participant real-names join gate + duplicate indicator.

Covers the participant's FIRST contact with the app (the join gate), end to end
through the real browser + Railway + daemon:

- First-visit single-field gate shown before the socket connects
- Enter submits the typed name; Anonymous ignores it (fictional name) + warning
- In-session duplicate indicator (blink + underline + ⚠️ + "duplicate" + click-to-change)
- Resolve-from-either-side clears the indicator for BOTH participants
- Rename via the crayon editor clears the indicator
- Returning participant skips the gate within the same session
- SECURITY: the participant_names_updated WS broadcast carries NO UUID
- Race: two participants Enter the same name — both admitted, both flagged
"""

import re
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

import pytest
from pages.participant_page import ParticipantPage
from playwright.sync_api import expect, sync_playwright
from session_utils import BASE, _wait_until, daemon_has_participant, fresh_session

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pw():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def browser(pw):
    b = pw.chromium.launch(headless=True)
    yield b
    b.close()


@pytest.fixture
def session_id():
    return fresh_session("RealNames")


# ── Helpers ─────────────────────────────────────────────────────────────────

def _open_pax(browser, session_id, capture_ws=False):
    """Open a fresh (first-visit) participant context. Returns (ctx, page, frames)."""
    ctx = browser.new_context()
    page = ctx.new_page()
    frames: list[str] = []
    if capture_ws:
        page.on(
            "websocket",
            lambda ws: ws.on("framereceived", lambda payload: frames.append(payload)),
        )
    page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
    return ctx, page, frames


def _gate(page):
    return page.locator("#name-gate")


def _dup_visible(page) -> bool:
    return page.locator("#dup-indicator").is_visible()


# ── 1. First-visit gate ──────────────────────────────────────────────────────

class TestFirstVisitGate:
    def test_gate_shown_before_socket_connects(self, browser, session_id):
        ctx, page, _ = _open_pax(browser, session_id)
        try:
            expect(_gate(page)).to_be_visible(timeout=10000)
            # Single free-text field with placeholder + attendance hint.
            inp = page.locator("#name-gate-input")
            expect(inp).to_be_visible()
            assert inp.get_attribute("placeholder")
            expect(page.locator(".name-gate-hint")).to_contain_text("attendance")
            # The WS is NOT connected yet — the gate is a hard pre-connect barrier.
            assert page.evaluate("() => (typeof _ws === 'undefined') || _ws === null")
            # Display name (session UI) is not shown behind the gate.
            expect(page.locator("#display-name")).to_be_hidden()
        finally:
            ctx.close()

    def test_enter_disabled_until_nonempty(self, browser, session_id):
        ctx, page, _ = _open_pax(browser, session_id)
        try:
            expect(_gate(page)).to_be_visible(timeout=10000)
            enter = page.locator("#name-gate-enter")
            expect(enter).to_be_disabled()
            page.locator("#name-gate-input").fill("   ")  # whitespace-only
            expect(enter).to_be_disabled()
            page.locator("#name-gate-input").fill("Ada")
            expect(enter).to_be_enabled()
        finally:
            ctx.close()

    def test_enter_submits_typed_name(self, browser, session_id):
        ctx, page, _ = _open_pax(browser, session_id)
        try:
            expect(_gate(page)).to_be_visible(timeout=10000)
            page.locator("#name-gate-input").fill("Ada Lovelace")
            page.locator("#name-gate-enter").click()
            expect(page.locator("#display-name .display-name-text")).to_have_text(
                "Ada Lovelace", timeout=10000
            )
            _wait_host(session_id, "Ada Lovelace")
        finally:
            ctx.close()

    def test_anonymous_ignores_typed_text(self, browser, session_id):
        ctx, page, _ = _open_pax(browser, session_id)
        try:
            expect(_gate(page)).to_be_visible(timeout=10000)
            # Warning present as hover text + tooltip title.
            anon = page.locator("#name-gate-anon")
            assert "attendance sheet" in (anon.get_attribute("title") or "")
            expect(page.locator("#name-gate-anon-warning")).to_contain_text(
                "attendance sheet"
            )
            page.locator("#name-gate-input").fill("TypedButIgnored")
            anon.click()
            expect(page.locator("#display-name .display-name-text")).not_to_be_empty(
                timeout=10000
            )
            name = page.locator("#display-name .display-name-text").inner_text().strip()
            assert name != "TypedButIgnored", "Anonymous must ignore the typed text"
        finally:
            ctx.close()


# ── 2. Returning participant skips the gate (same session) ───────────────────

class TestReturningSkipsGate:
    def test_returning_same_session_no_gate(self, browser, session_id):
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
            expect(_gate(page)).to_be_visible(timeout=10000)
            page.locator("#name-gate-input").fill("Grace Hopper")
            page.locator("#name-gate-enter").click()
            expect(page.locator("#display-name .display-name-text")).to_have_text(
                "Grace Hopper", timeout=10000
            )
            # Reload within the same session: same UUID → committed name → no gate.
            page.reload(wait_until="networkidle")
            expect(page.locator("#display-name .display-name-text")).to_have_text(
                "Grace Hopper", timeout=10000
            )
            # The gate must NOT reappear.
            assert not _gate(page).is_visible()
        finally:
            ctx.close()


# ── 2b. Gate reappears on a new session ──────────────────────────────────────

class TestGateReappearsNewSession:
    @pytest.mark.nightly
    def test_new_session_shows_gate_again(self, browser, session_id):
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
            expect(_gate(page)).to_be_visible(timeout=10000)
            page.locator("#name-gate-input").fill("Judy")
            page.locator("#name-gate-enter").click()
            expect(page.locator("#display-name .display-name-text")).to_have_text(
                "Judy", timeout=10000
            )
            # A brand-new session resets participant state; the SAME browser/UUID
            # is now unknown to the server → the gate must reappear.
            session2 = fresh_session("RealNames2")
            page.goto(f"{BASE}/{session2}", wait_until="networkidle")
            expect(_gate(page)).to_be_visible(timeout=15000)
        finally:
            ctx.close()


# ── 3. In-session duplicate indicator ────────────────────────────────────────

class TestDuplicateIndicator:
    def _join(self, browser, session_id, name, capture_ws=False):
        ctx, page, frames = _open_pax(browser, session_id, capture_ws=capture_ws)
        expect(_gate(page)).to_be_visible(timeout=10000)
        page.locator("#name-gate-input").fill(name)
        page.locator("#name-gate-enter").click()
        expect(page.locator("#display-name .display-name-text")).to_have_text(
            name, timeout=10000
        )
        return ctx, page, frames

    def test_duplicate_shows_all_indicator_parts_on_both(self, browser, session_id):
        ctxA, pageA, _ = self._join(browser, session_id, "Dana")
        ctxB, pageB, _ = self._join(browser, session_id, "Dana")
        try:
            for page in (pageA, pageB):
                # Own card: blink + underline (class), ⚠️ prefix, label + click-to-change.
                expect(page.locator("#dup-indicator")).to_be_visible(timeout=10000)
                expect(page.locator("#dup-indicator")).to_contain_text("duplicate")
                expect(page.locator("#dup-indicator")).to_contain_text("click here to change")
                expect(page.locator("#dup-name-prefix")).to_be_visible()
                assert "name-duplicate" in (
                    page.locator("#display-name .display-name-text").get_attribute("class") or ""
                )
        finally:
            ctxA.close()
            ctxB.close()

    def test_resolve_from_either_side_clears_both(self, browser, session_id):
        ctxA, pageA, _ = self._join(browser, session_id, "Echo")
        ctxB, pageB, _ = self._join(browser, session_id, "Echo")
        try:
            expect(pageA.locator("#dup-indicator")).to_be_visible(timeout=10000)
            expect(pageB.locator("#dup-indicator")).to_be_visible(timeout=10000)
            # A renames to a unique name via the crayon editor.
            ParticipantPage(pageA).rename("Echo-Unique")
            # Both indicators clear (each recomputes from the re-broadcast list).
            expect(pageA.locator("#dup-indicator")).to_be_hidden(timeout=10000)
            expect(pageB.locator("#dup-indicator")).to_be_hidden(timeout=10000)
        finally:
            ctxA.close()
            ctxB.close()

    def test_click_to_change_opens_crayon_editor(self, browser, session_id):
        ctxA, pageA, _ = self._join(browser, session_id, "Fay")
        ctxB, pageB, _ = self._join(browser, session_id, "Fay")
        try:
            expect(pageA.locator("#dup-indicator")).to_be_visible(timeout=10000)
            pageA.locator("#dup-indicator .dup-change-link").click()
            expect(pageA.locator("#name-edit-input")).to_be_visible(timeout=5000)
        finally:
            ctxA.close()
            ctxB.close()


# ── 4. SECURITY: no UUID in the participant names broadcast ───────────────────

class TestNoUuidBroadcast:
    def test_names_broadcast_carries_no_uuid(self, browser, session_id):
        # Capture WS frames on participant A while participant B joins/renames.
        ctxA, pageA, frames = _open_pax(browser, session_id, capture_ws=True)
        try:
            expect(_gate(pageA)).to_be_visible(timeout=10000)
            pageA.locator("#name-gate-input").fill("Gwen")
            pageA.locator("#name-gate-enter").click()
            expect(pageA.locator("#display-name .display-name-text")).to_have_text(
                "Gwen", timeout=10000
            )
            # A second participant joins → triggers a names broadcast to A.
            ctxB, pageB, _ = _open_pax(browser, session_id)
            expect(_gate(pageB)).to_be_visible(timeout=10000)
            pageB.locator("#name-gate-input").fill("Heidi")
            pageB.locator("#name-gate-enter").click()
            expect(pageB.locator("#display-name .display-name-text")).to_have_text(
                "Heidi", timeout=10000
            )
            # Wait for A to receive at least one names broadcast with both names.
            _wait_until(lambda: any(
                "participant_names_updated" in f and "Heidi" in f for f in frames
            ), timeout_ms=10000, msg="A never received a names broadcast including Heidi")
            name_frames = [f for f in frames if "participant_names_updated" in f]
            assert name_frames, "no participant_names_updated frames captured"
            for f in name_frames:
                assert not _UUID_RE.search(f), f"UUID leaked in names broadcast: {f}"
                assert '"names"' in f  # names-only payload
            ctxB.close()
        finally:
            ctxA.close()


# ── 5. Race: two participants Enter the same name at once ────────────────────

class TestConcurrentSameName:
    def test_both_admitted_and_flagged(self, browser, session_id):
        ctxA, pageA, _ = _open_pax(browser, session_id)
        ctxB, pageB, _ = _open_pax(browser, session_id)
        try:
            for page in (pageA, pageB):
                expect(_gate(page)).to_be_visible(timeout=10000)
                page.locator("#name-gate-input").fill("Ivy")
            # Fire both Enters as close together as possible.
            pageA.locator("#name-gate-enter").click()
            pageB.locator("#name-gate-enter").click()
            # Both admitted under "Ivy" (no 409, no dead end).
            expect(pageA.locator("#display-name .display-name-text")).to_have_text(
                "Ivy", timeout=10000
            )
            expect(pageB.locator("#display-name .display-name-text")).to_have_text(
                "Ivy", timeout=10000
            )
            _wait_host(session_id, "Ivy")
            # Both observe the duplicate indicator.
            expect(pageA.locator("#dup-indicator")).to_be_visible(timeout=10000)
            expect(pageB.locator("#dup-indicator")).to_be_visible(timeout=10000)
        finally:
            ctxA.close()
            ctxB.close()


# ── shared waits ─────────────────────────────────────────────────────────────

def _wait_host(session_id, name):
    # daemon_has_participant already swallows transient request errors.
    _wait_until(lambda: daemon_has_participant(session_id, name),
                timeout_ms=10000,
                msg=f"host never saw participant {name!r}")
