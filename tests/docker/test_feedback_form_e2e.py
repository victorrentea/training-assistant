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
from session_utils import fresh_session

pytestmark = pytest.mark.nightly

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
SESSIONS_FOLDER = os.environ.get("SESSIONS_FOLDER", "/tmp/test-sessions")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")

# Written by daemon/lock.py — the only reliable handle on the running daemon PID.
LOCK_FILE = Path("/tmp/training_daemon.lock")

_HERE = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.environ.get("APP_ROOT") or (
    "/app" if os.path.isdir("/app") else os.path.normpath(os.path.join(_HERE, "..", ".."))
)

FORM_URL = "https://freeonlinesurveys.com/s/demo1234"
RESTART_FORM_URL = "https://freeonlinesurveys.com/s/restart42"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _await_condition(fn, timeout_ms=10000, poll_ms=300, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def _get_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return {}


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


def _restart_daemon(session_id: str) -> int:
    """Kill the running daemon and start a fresh one; return the new PID.

    This is a genuine process restart: every byte of in-memory daemon state is
    gone, so anything still visible afterwards came back off the disk.
    """
    old_pid = _daemon_pid()
    os.kill(old_pid, signal.SIGTERM)
    deadline = time.monotonic() + 15
    while _pid_alive(old_pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    if _pid_alive(old_pid):
        os.kill(old_pid, signal.SIGKILL)
        _await_condition(
            lambda: not _pid_alive(old_pid),
            timeout_ms=10000,
            msg=f"Daemon PID {old_pid} survived SIGKILL",
        )
    print(f"[restart] old daemon PID {old_pid} is gone")

    env = os.environ.copy()
    env["OTEL_SERVICE_NAME"] = "Daemon"
    subprocess.Popen([sys.executable, "-m", "daemon"], cwd=APP_ROOT, env=env)

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
        expect(row).to_be_hidden(timeout=5000)
        expect(cta).to_be_hidden(timeout=3000)

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
