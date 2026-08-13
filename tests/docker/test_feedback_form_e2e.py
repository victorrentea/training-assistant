"""Hermetic E2E: the end-of-session feedback form link reaches participants.

Two behaviours are worth the cost of a full-stack run:

1. Live delivery — publishing the form must reveal the left-nav entry on an
   already-connected participant, through the WS broadcast path, with no reload.
2. Restart survival — the daemon auto-restarts on every push to master. Unlike
   its sibling ``gdrive_url`` (re-resolved from DriveFS at boot), the feedback
   URL exists only in ``<session folder>/feedback-form.json``. If the boot-time
   restore regresses, the link silently vanishes from participant screens
   mid-session. Here the daemon process is really killed and really restarted.
"""

import base64
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

from pages.participant_page import ParticipantPage
from playwright.sync_api import expect, sync_playwright
from session_utils import _get_json, _req, fresh_session

pytestmark = pytest.mark.nightly

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
SESSIONS_FOLDER = os.environ.get("SESSIONS_FOLDER", "/tmp/test-sessions")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")

# Written by daemon/lock.py — the only reliable handle on the running daemon PID.
LOCK_FILE = Path("/tmp/training_daemon.lock")

APP_ROOT = "/app"  # these tests only ever run inside the hermetic image

# Daemon instances this module spawned, so they can be reaped. A process we
# started and never wait() on becomes a zombie, and a zombie still answers
# os.kill(pid, 0) — a later restart would then wait out every timeout on a
# process that is already dead.
_spawned_daemons: list[subprocess.Popen] = []

FORM_URL = "https://freeonlinesurveys.com/s/demo1234"
RESTART_FORM_URL = "https://freeonlinesurveys.com/s/restart42"
RETRACT_FORM_URL = "https://freeonlinesurveys.com/s/oops99"
LEAK_FORM_URL = "https://freeonlinesurveys.com/s/leak7x"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _await_condition(fn, timeout_ms=10000, poll_ms=300, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def _publish_feedback_form(title: str, url: str) -> dict:
    """POST the host-machine-local /feedback-form route (no session id in path)."""
    req = urllib.request.Request(
        f"{DAEMON_BASE}/feedback-form",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"title": title, "url": url}).encode(),
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        assert resp.status == 200, f"POST /feedback-form returned {resp.status}"
        return json.loads(resp.read())


def _retract_feedback_form() -> dict:
    """DELETE the host-machine-local /feedback-form route — the undo for a bad publish."""
    req = urllib.request.Request(f"{DAEMON_BASE}/feedback-form", method="DELETE")
    with urllib.request.urlopen(req, timeout=15) as resp:
        assert resp.status == 200, f"DELETE /feedback-form returned {resp.status}"
        return json.loads(resp.read())


def _participant_feedback_url() -> str | None:
    """The feedback URL the daemon would hand a participant joining right now."""
    return _get_json(f"{DAEMON_BASE}/api/participant/state").get("feedback_url")


def _end_session() -> None:
    try:
        _req("POST", f"{DAEMON_BASE}/api/session/end")
    except json.JSONDecodeError:
        pass  # /end answers 204 with an empty body; only the decode is tolerated

    _await_condition(
        lambda: _get_json(f"{DAEMON_BASE}/api/session/active").get("session_id", "?") is None,
        msg="Daemon still reports an active session after /end",
    )


def _resume_session(folder_name: str) -> str:
    """Re-enter an existing session folder; returns its session_id.

    Requires no active session: the daemon only re-resolves per-session state
    (gdrive_url, feedback form, participant caches) when it enters a session
    from an empty stack.
    """
    result = _req(
        "POST",
        f"{DAEMON_BASE}/api/session/resume",
        json.dumps({"folder": folder_name}).encode(),
    )
    session_id = result["session_id"]
    _await_condition(
        lambda: _get_json(f"{DAEMON_BASE}/api/session/active").get("session_id") == session_id,
        timeout_ms=20000,
        msg=f"Daemon did not enter resumed session {folder_name!r}",
    )
    return session_id


def _active_session_folder_name(session_id: str) -> str:
    """Return the active session's folder name, read from the daemon host state."""
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    req = urllib.request.Request(
        f"{DAEMON_BASE}/api/{session_id}/host/state",
        headers={"Authorization": f"Basic {auth}"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        name = json.loads(resp.read()).get("daemon_session_folder")
    assert name, "Daemon host state reports no active session folder"
    return name


def _daemon_pid() -> int:
    return int(json.loads(LOCK_FILE.read_text())["pid"])


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _kill_daemon(pid: int) -> None:
    """SIGTERM the daemon, escalate to SIGKILL, and make sure it is really gone.

    A daemon this module spawned must be reaped with wait(), not merely killed:
    an unreaped child lingers as a zombie that os.kill(pid, 0) still reports as
    alive, so the next restart would burn both timeouts and fail spuriously. The
    very first daemon is a child of the harness shell, which reaps it for us —
    that one can only be polled.
    """
    ours = next((p for p in _spawned_daemons if p.pid == pid), None)
    os.kill(pid, signal.SIGTERM)
    if ours is not None:
        try:
            ours.wait(timeout=15)
        except subprocess.TimeoutExpired:
            ours.kill()
            ours.wait(timeout=10)
        _spawned_daemons.remove(ours)
        return
    deadline = time.monotonic() + 15
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    if _pid_alive(pid):
        os.kill(pid, signal.SIGKILL)
        _await_condition(
            lambda: not _pid_alive(pid),
            timeout_ms=10000,
            msg=f"Daemon PID {pid} survived SIGKILL",
        )


def _restart_daemon(session_id: str) -> int:
    """Kill the running daemon and start a fresh one; return the new PID.

    This is a genuine process restart: every byte of in-memory daemon state is
    gone, so anything still visible afterwards came back off the disk.
    """
    old_pid = _daemon_pid()
    _kill_daemon(old_pid)
    print(f"[restart] old daemon PID {old_pid} is gone")

    env = os.environ.copy()
    env["OTEL_SERVICE_NAME"] = "Daemon"
    _spawned_daemons.append(
        subprocess.Popen([sys.executable, "-m", "daemon"], cwd=APP_ROOT, env=env)
    )

    # The new instance is up once it has re-adopted the active session…
    _await_condition(
        lambda: _get_json(f"{DAEMON_BASE}/api/session/active").get("session_id") == session_id,
        timeout_ms=60000,
        msg=f"Restarted daemon did not re-adopt session {session_id!r}",
    )
    # …and once Railway can proxy to it again (so later tests are unaffected).
    _await_condition(
        lambda: _get_json(f"{BASE}/{session_id}/api/status").get("session_id") == session_id,
        timeout_ms=30000,
        msg="Railway did not reconnect to the restarted daemon",
    )
    new_pid = _daemon_pid()
    assert new_pid != old_pid, (
        f"Daemon was not actually restarted — lock file still holds PID {new_pid}"
    )
    print(f"[restart] new daemon PID {new_pid} is serving session {session_id}")
    return new_pid


# ── Tests ────────────────────────────────────────────────────────────────────


def test_feedback_link_appears_live_without_reload():
    """Publishing the form reveals the nav item on an already-connected participant."""
    session_id = fresh_session("FeedbackLive")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context().new_page()
        page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        ParticipantPage(page).join("FeedbackTester")

        row = page.locator("#feedback-row")
        cta = page.locator("#feedback-cta")

        # Nothing published yet — both the nav entry and the CTA stay hidden.
        # to_be_hidden() alone is also satisfied by an absent element, which would
        # make a typo'd selector look like a passing pre-condition.
        expect(row).to_have_count(1, timeout=5000)
        expect(cta).to_have_count(1, timeout=3000)
        expect(row).to_be_hidden()
        expect(cta).to_be_hidden()

        published = _publish_feedback_form("AI@Acme", FORM_URL)
        assert published["url"] == FORM_URL
        assert published["created_at"], "Expected an ISO created_at in the response"

        # No reload: the broadcast alone must reveal the entry.
        expect(row).to_be_visible(timeout=10000)
        assert page.locator("#feedback-nav").get_attribute("href") == FORM_URL
        expect(cta).to_be_visible(timeout=10000)
        assert page.locator("#feedback-cta-link").get_attribute("href") == FORM_URL

        # The nav entry is the last one in the left nav (after "About Victor").
        assert page.locator("aside nav > *").last.get_attribute("id") == "feedback-row"

        browser.close()

    # Persisted alongside the session, not only in memory.
    form_file = (
        Path(SESSIONS_FOLDER) / _active_session_folder_name(session_id) / "feedback-form.json"
    )
    assert form_file.exists(), f"{form_file} was not written"
    assert json.loads(form_file.read_text())["url"] == FORM_URL


def test_feedback_link_survives_daemon_restart():
    """The regression this feature exists to prevent: a push to master restarts the
    daemon, and the link must still reach participants afterwards."""
    session_id = fresh_session("FeedbackRestart")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context().new_page()
        page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        ParticipantPage(page).join("RestartTester")

        _publish_feedback_form("DDD@ING", RESTART_FORM_URL)
        expect(page.locator("#feedback-row")).to_be_visible(timeout=10000)

        _restart_daemon(session_id)

        # A fresh load takes the URL from the participant state payload, which is
        # only populated if the daemon restored it from the session folder at boot.
        page.reload(wait_until="networkidle")
        ParticipantPage(page).dismiss_gate_anonymous(timeout=3000)
        expect(page.locator("#feedback-row")).to_be_visible(timeout=20000)
        assert page.locator("#feedback-nav").get_attribute("href") == RESTART_FORM_URL

        browser.close()

    # Belt and braces: the state payload itself carries the restored URL.
    state = _get_json(f"{DAEMON_BASE}/api/participant/state")
    assert state.get("feedback_url") == RESTART_FORM_URL, (
        f"Participant state lost feedback_url after restart: {state.get('feedback_url')!r}"
    )


def test_retracting_the_form_hides_it_live_from_participants():
    """The undo for a wrong publish, all the way to the browser.

    Publishing has no host allowlist by design, so a bad link genuinely reaches
    the room (it did once during this feature's development). This is the only
    exercise of the clear direction of ``_applyFeedbackUrl`` — hiding a row and a
    CTA that were previously shown, and resetting both hrefs so a stale link
    cannot be clicked out of a hidden element.
    """
    session_id = fresh_session("FeedbackRetract")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context().new_page()
        page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        ParticipantPage(page).join("RetractTester")

        row = page.locator("#feedback-row")
        cta = page.locator("#feedback-cta")

        _publish_feedback_form("Oops", RETRACT_FORM_URL)
        expect(row).to_be_visible(timeout=10000)
        expect(cta).to_be_visible(timeout=10000)

        assert _retract_feedback_form() == {"retracted": True}

        # No reload: the null broadcast alone must take it back off the screen.
        expect(row).to_be_hidden(timeout=10000)
        expect(cta).to_be_hidden(timeout=10000)
        assert page.locator("#feedback-nav").get_attribute("href") == "#"
        assert page.locator("#feedback-cta-link").get_attribute("href") == "#"

        browser.close()

    # The marker is deleted, not blanked — otherwise the next restart brings it back.
    form_file = (
        Path(SESSIONS_FOLDER) / _active_session_folder_name(session_id) / "feedback-form.json"
    )
    assert not form_file.exists(), f"{form_file} survived the retraction"
    assert _participant_feedback_url() is None
    # Idempotent: a caller that retries blindly gets a success, not a 404/500.
    assert _retract_feedback_form() == {"retracted": False}


def test_feedback_link_does_not_leak_into_the_next_clients_session():
    """Entering another session must re-resolve the feedback URL from its folder.

    The defect this guards: yesterday's client's form staying live in today's
    room. Both directions of the switch are exercised against the real daemon —
    entering a session with no form clears it, entering one whose form was
    published restores it. The restore direction is what pins the session-switch
    call site specifically: ending a session also clears the URL, but nothing
    except the enter path can bring it back.
    """
    session_a = fresh_session("FeedbackLeakA")
    folder_a = _active_session_folder_name(session_a)
    _publish_feedback_form("AI@Acme", LEAK_FORM_URL)
    assert _participant_feedback_url() == LEAK_FORM_URL

    # ── Into the next client's session: the previous form must not follow ──
    session_b = fresh_session("FeedbackLeakB")
    assert _participant_feedback_url() is None, (
        "Previous session's feedback form is still live in the new session"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context().new_page()
        page.goto(f"{BASE}/{session_b}", wait_until="networkidle")
        ParticipantPage(page).join("LeakTester")
        expect(page.locator("#feedback-row")).to_have_count(1, timeout=5000)
        expect(page.locator("#feedback-row")).to_be_hidden()
        expect(page.locator("#feedback-cta")).to_be_hidden()
        browser.close()

    # ── Back into the first session: its own form is restored from its folder ──
    _end_session()
    resumed = _resume_session(folder_a)
    assert resumed == session_a, "Resuming a folder must keep its persistent session_id"
    _await_condition(
        lambda: _participant_feedback_url() == LEAK_FORM_URL,
        timeout_ms=15000,
        msg="Resumed session did not restore its own feedback form",
    )

    # Leave the daemon clean for whatever runs next.
    _retract_feedback_form()
