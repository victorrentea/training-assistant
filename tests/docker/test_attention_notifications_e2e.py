"""
Hermetic E2E: attention notifications (host 🔔 master switch + host notification).

Drives the real backend + daemon + two browser contexts and proves the
end-to-end phase-1 behaviour:

  master switch OFF (default) -> participant has NO bell button, NO permission bar
  switch ON (host click)      -> bell button + permission bar appear LIVE (no reload)
  participant rings the bell  -> host page renders the incoming bell (dual-render)
  host sends a notification   -> reaches the participant (granted -> Notification)
  switch OFF again            -> bell button + permission bar disappear LIVE

Marked nightly (two browser contexts, multi-phase → > 5s).
"""

import os
import sys
import time

import pytest

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

from playwright.sync_api import sync_playwright, expect

from pages.participant_page import ParticipantPage
from session_utils import fresh_session, daemon_has_participant


BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


# Stub the Notification API so the "granted" branch is deterministic and
# capturable in headless Chromium (which has no real OS notification surface).
_NOTIF_STUB = """
window.__notifs = [];
class FakeNotification {
  constructor(title, opts) { window.__notifs.push(String(title)); }
  static get permission() { return 'granted'; }
  static requestPermission(cb) { if (cb) cb('granted'); return Promise.resolve('granted'); }
}
window.Notification = FakeNotification;
"""


def _await_condition(fn, timeout_ms=10000, poll_ms=300, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def _await_badge_state(host_page, expected, timeout_ms=5000):
    badge = host_page.locator("#attention-master-badge")
    _await_condition(
        lambda: expected in (badge.get_attribute("class") or ""),
        timeout_ms=timeout_ms,
        msg=f"attention-master-badge never became '{expected}'",
    )


@pytest.mark.nightly
def test_attention_master_switch_and_notification():
    session_id = fresh_session("AttentionE2E")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ── Host
        host_ctx = browser.new_context(
            http_credentials={"username": HOST_USER, "password": HOST_PASS}
        )
        host_page = host_ctx.new_page()
        host_page.goto(f"{DAEMON_BASE}/host/{session_id}", wait_until="networkidle")
        expect(host_page.locator("#tab-quiz")).to_be_visible(timeout=10000)
        # Attention badge starts DISABLED (default OFF, reset every session).
        _await_badge_state(host_page, "disabled")

        # ── Participant (Notification API stubbed + permission pre-granted)
        pax_ctx = browser.new_context(permissions=["notifications"])
        pax_ctx.add_init_script(_NOTIF_STUB)
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("Ringer")
        _await_condition(
            lambda: daemon_has_participant(session_id, "Ringer"),
            timeout_ms=5000,
            msg="Host does not see 'Ringer'",
        )

        # ── Phase 0: while OFF, no bell button, no permission bar
        assert pax_page.locator("#attention-bell-btn").count() == 0
        assert not pax_page.locator("#attention-permission-bar").is_visible()
        print("Phase 0 OK: nothing shown while attention OFF")

        # ── Phase 1: host enables → bell + permission bar appear LIVE (no reload)
        host_page.locator("#attention-master-badge").click()
        _await_badge_state(host_page, "connected")
        expect(pax_page.locator("#attention-bell-btn")).to_be_visible(timeout=5000)
        expect(pax_page.locator("#attention-permission-bar")).to_be_visible(timeout=5000)
        print("Phase 1 OK: bell + permission bar appeared live")

        # ── Phase 2: participant rings the bell → host page dual-renders it
        pax_page.locator("#attention-bell-btn").click(force=True)
        _await_condition(
            lambda: "is calling you" in (host_page.locator("#toast").inner_text() or ""),
            timeout_ms=5000,
            msg="Host did not render the incoming bell",
        )
        print("Phase 2 OK: host rendered the incoming bell (dual-render)")

        # ── Phase 3: host broadcasts a notification → reaches the participant
        text = "We are resuming — please come back"
        host_page.locator("#attention-notify-badge").click()
        inp = host_page.locator("#attention-notify-input")
        inp.wait_for(state="visible", timeout=3000)
        inp.fill(text)
        host_page.locator("#attention-notify-btn").click()
        _await_condition(
            lambda: text in (pax_page.evaluate("window.__notifs || []") or []),
            timeout_ms=5000,
            msg="Participant never received the host notification",
        )
        print("Phase 3 OK: host_notification delivered to participant (granted branch)")

        # ── Phase 4: host disables → bell + permission bar disappear LIVE
        host_page.locator("#attention-master-badge").click()
        _await_badge_state(host_page, "disabled")
        expect(pax_page.locator("#attention-bell-btn")).to_have_count(0, timeout=5000)
        _await_condition(
            lambda: not pax_page.locator("#attention-permission-bar").is_visible(),
            timeout_ms=5000,
            msg="Permission bar did not hide after disabling",
        )
        print("Phase 4 OK: bell + permission bar removed live after disabling")

        browser.close()
