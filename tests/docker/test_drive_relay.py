"""Hermetic E2E tests for the Google Drive relay.

Real backend + mock Drive API v3 server (see mock_drive_server.py), no browser
needed — the relay is plain HTTP. The critical scenario, which no unit test
can prove, is test_download_works_with_the_daemon_stopped: participants fetch
course materials after the workshop, when the trainer's laptop (and therefore
the daemon) is closed. The relay must never depend on it.
"""

import io
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import pytest

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
DAEMON_LOCK_FILE = "/tmp/training_daemon.lock"

ROOT_ID = "rootfolder0000000000"
STRANGER_ID = "stranger000000000000"


def drive_url(file_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{file_id}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface a 3xx as the response itself instead of silently following it."""

    def redirect_request(self, *args, **kwargs):
        return None


_no_redirect_opener = urllib.request.build_opener(_NoRedirect)


def _get(path: str, params: dict, *, follow_redirects: bool = True):
    """GET against BASE, returning (status, headers, body) without raising on 4xx/5xx.

    ``headers`` is the original case-insensitive email.message.Message — do not
    collapse it into a plain dict, or lookups like headers.get("Content-Type")
    silently miss the wire-lowercased "content-type" key.
    """
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    opener = urllib.request.urlopen if follow_redirects else _no_redirect_opener.open
    try:
        with opener(url, timeout=60) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


# ── stopped_daemon fixture ──────────────────────────────────────────────────
#
# There is no docker-compose here: backend, daemon and the mock servers all run
# as processes inside one container (tests/docker/start_hermetic.sh). To prove
# the relay survives "the trainer's laptop is closed", this fixture stops the
# real daemon process, lets the test run, and always restarts it afterwards —
# the container is shared by every test in the run, so leaving the daemon dead
# would fail everything that follows.


def _daemon_pid() -> int:
    with open(DAEMON_LOCK_FILE, encoding="utf-8") as f:
        return int(json.load(f)["pid"])


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _daemon_reachable() -> bool:
    try:
        urllib.request.urlopen(f"{DAEMON_BASE}/host", timeout=2)
        return True
    except Exception:
        return False


def _wait_until(predicate, timeout=20.0, interval=0.3, msg="condition not met"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"Timed out after {timeout}s: {msg}")


@pytest.fixture
def stopped_daemon():
    """Stop the real daemon process for the test body, then bring it back."""
    pid = _daemon_pid()
    os.kill(pid, signal.SIGTERM)
    _wait_until(lambda: not _process_alive(pid), msg="daemon process did not exit")
    _wait_until(lambda: not _daemon_reachable(), msg="daemon host server did not go down")

    try:
        yield
    finally:
        env = dict(os.environ, OTEL_SERVICE_NAME="Daemon")
        subprocess.Popen([sys.executable, "-m", "daemon"], cwd="/app", env=env)
        _wait_until(_daemon_reachable, timeout=30.0, msg="daemon did not come back up after the test")


# ── tests ────────────────────────────────────────────────────────────────────


def test_preview_describes_the_folder():
    status, _, body = _get("/api/drive/preview", {"url": drive_url(ROOT_ID)})

    assert status == 200
    payload = json.loads(body)
    assert payload["name"] == "Hermetic Materials"
    assert payload["file_count"] == 2
    assert payload["total_bytes"] == 8


def test_zip_contains_the_whole_tree():
    status, headers, body = _get("/api/drive/zip", {"url": drive_url(ROOT_ID)})

    assert status == 200
    assert headers.get("Content-Type") == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(body))
    assert archive.namelist() == ["Intro.pdf", "Day 2/Lab.pdf"]
    assert archive.read("Intro.pdf") == b"INTRO"
    assert archive.read("Day 2/Lab.pdf") == b"LAB"


def test_a_strangers_folder_is_refused():
    status, _, _ = _get("/api/drive/zip", {"url": drive_url(STRANGER_ID)})

    assert status == 404


def test_the_browser_is_never_redirected_to_google():
    status, headers, _ = _get(
        "/api/drive/zip", {"url": drive_url(ROOT_ID)}, follow_redirects=False
    )

    assert status == 200
    assert "Location" not in headers


def test_download_works_with_the_daemon_stopped(stopped_daemon):
    """The reason this feature exists: it must not depend on the trainer's laptop."""
    status, _, body = _get("/api/drive/zip", {"url": drive_url(ROOT_ID)})

    assert status == 200
    assert zipfile.ZipFile(io.BytesIO(body)).namelist() == ["Intro.pdf", "Day 2/Lab.pdf"]
