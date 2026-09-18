"""
Hermetic E2E: a 🤖 prompt landing in the notes fires an OS notification.

A 🤖 snippet is a prompt the trainer expects everyone to COPY, and the people who
need telling are exactly the ones already in their IDE with this tab behind it.
Unlike the host 🔔 notification, this path is gated on notification permission
alone — the attention master switch stays OFF for the whole test.

Proves:
  🤖 append, tab unfocused  -> Notification fired (title + truncated body)
  🤖 append, tab focused    -> NO notification (the copy toaster is already there)
  📋 append                 -> NO notification, ever (hand-sent lines stay silent)
  first 🤖 append           -> permission pill appears although attention is OFF

Marked nightly (browser context + several file-watch round trips → > 5s).
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
from session_utils import daemon_has_participant, fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
SESSIONS_FOLDER = os.environ.get("SESSIONS_FOLDER", "/tmp/test-sessions")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")

ROBOT = "\U0001f916"
CLIPBOARD = "\U0001f4cb"

# Stub the Notification API so the "granted" branch is deterministic and
# capturable in headless Chromium (which has no real OS notification surface),
# and make document.hasFocus() steerable so both focus branches are testable
# without fighting Chromium's real focus model.
_NOTIF_STUB = """
window.__notifs = [];
window.__focused = false;
document.hasFocus = function() { return window.__focused; };
class FakeNotification {
  constructor(title, opts) {
    window.__notifs.push({ title: String(title), body: String((opts && opts.body) || ''),
                           tag: String((opts && opts.tag) || '') });
  }
  close() {}
  static get permission() { return 'granted'; }
  static requestPermission(cb) { if (cb) cb('granted'); return Promise.resolve('granted'); }
}
window.Notification = FakeNotification;
"""


def _await_condition(fn, timeout_ms=10000, poll_ms=200, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        try:
            result = fn()
            if result:
                return result
        except Exception:
            pass
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def _get_active_session_name(session_id: str) -> str | None:
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    req = urllib.request.Request(
        f"{DAEMON_BASE}/api/{session_id}/host/state",
        headers={"Authorization": f"Basic {auth}"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read()).get("daemon_session_folder")


def _notes_path(session_name: str) -> str:
    folder = os.path.join(SESSIONS_FOLDER, session_name)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "notes.txt")


def _append_note(session_name: str, line: str) -> None:
    """Append one line, the way the macOS addon does.

    The daemon only toasts a *pure append* to an already-seen, non-empty notes
    file, so every test append lands on top of the baseline written first.
    """
    with open(_notes_path(session_name), "a") as f:
        f.write(line + "\n")


@pytest.mark.nightly
def test_robot_prompt_fires_os_notification():
    session_id = fresh_session("PromptNotifyE2E")
    session_name = _await_condition(
        lambda: _get_active_session_name(session_id),
        timeout_ms=10000,
        msg="Daemon never reported an active session folder",
    )

    # Baseline notes file: the daemon needs a previous non-empty text to diff
    # an append against (an initial probe is intentionally silent).
    with open(_notes_path(session_name), "w") as f:
        f.write("Baseline line\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pax_ctx = browser.new_context(permissions=["notifications"])
        pax_ctx.add_init_script(_NOTIF_STUB)
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("Copier")
        _await_condition(
            lambda: daemon_has_participant(session_id, "Copier"),
            timeout_ms=5000,
            msg="Daemon does not see 'Copier'",
        )

        # Let the daemon observe the baseline before the first append, so the
        # append really reads as an append and not as the initial probe.
        _await_condition(
            lambda: pax_page.locator('[data-nav="notes"]').is_visible(),
            timeout_ms=10000,
            msg="Notes nav never appeared — daemon did not pick up the baseline",
        )

        # Attention stays OFF for the whole test: permission is the only gate.
        assert pax_page.locator("#attention-bell-btn").count() == 0
        assert not pax_page.locator("#attention-permission-bar").is_visible()

        # ── Phase 1: 🤖 prompt, tab unfocused → notification fires
        long_prompt = "Refactor the OrderService " + ("very " * 60) + "carefully"
        _append_note(session_name, f"{ROBOT} {long_prompt}")
        notif = _await_condition(
            lambda: (pax_page.evaluate("window.__notifs") or [None])[0],
            timeout_ms=15000,
            msg="No OS notification fired for the 🤖 prompt",
        )
        assert notif["title"] == f"{ROBOT} New prompt to copy"
        assert notif["tag"] == "prompt"
        assert len(notif["body"]) <= 180, f"body not truncated: {len(notif['body'])}"
        assert notif["body"].endswith("…"), "truncated body should end with an ellipsis"
        assert notif["body"].startswith("Refactor the OrderService")
        assert ROBOT not in notif["body"], "the marker is metadata, not content"
        print("Phase 1 OK: 🤖 prompt fired an OS notification while unfocused")

        # ── Phase 2: the permission pill appeared although attention is OFF
        expect(pax_page.locator("#attention-permission-bar")).to_be_visible(timeout=5000)
        assert pax_page.locator("#attention-bell-btn").count() == 0, "bell must stay gated"
        print("Phase 2 OK: permission pill shown with attention OFF, bell still hidden")

        # ── Phase 3: 📋 hand-sent line → silent
        _append_note(session_name, f"{CLIPBOARD} https://example.com/handout")
        _await_condition(
            lambda: "example.com/handout" in pax_page.locator("body").inner_text(),
            timeout_ms=15000,
            msg="The 📋 snippet never reached the participant at all",
        )
        assert len(pax_page.evaluate("window.__notifs")) == 1, "📋 line must not notify"
        print("Phase 3 OK: 📋 hand-sent line toasted but did not notify")

        # ── Phase 4: 🤖 prompt while the tab IS focused → silent
        pax_page.evaluate("window.__focused = true")
        _append_note(session_name, f"{ROBOT} Second prompt while focused")
        _await_condition(
            lambda: "Second prompt while focused" in pax_page.locator("body").inner_text(),
            timeout_ms=15000,
            msg="The second 🤖 snippet never reached the participant at all",
        )
        assert len(pax_page.evaluate("window.__notifs")) == 1, (
            "a focused tab already shows the copy toaster — no OS ping"
        )
        print("Phase 4 OK: focused tab got the toaster but no OS notification")

        browser.close()
