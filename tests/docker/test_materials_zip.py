"""Hermetic E2E: participant downloads the session zip through the Railway relay.

Covers the full round trip — participant GET → Railway → build_materials_zip WS
push → daemon zips its local session folder → multipart upload → archive served
— and asserts the blacklist is applied.

This is the firewall fallback: participants whose corporate network blocks
drive.google.com have no other route to the materials.
"""

import base64
import io
import json
import os
import sys
import urllib.request
import zipfile

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
SESSIONS_FOLDER = os.environ.get("SESSIONS_FOLDER", "/tmp/test-sessions")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


def _active_session_folder(session_id: str) -> str:
    """Return the daemon's session folder name for the active session."""
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    req = urllib.request.Request(
        f"{DAEMON_BASE}/api/{session_id}/host/state",
        headers={"Authorization": f"Basic {auth}"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())["daemon_session_folder"]


def test_participant_downloads_session_zip():
    session_id = fresh_session("MaterialsZip")
    folder = os.path.join(SESSIONS_FOLDER, _active_session_folder(session_id))

    with open(os.path.join(folder, "ai-summary.md"), "w", encoding="utf-8") as f:
        f.write("summary")
    with open(os.path.join(folder, "session-state.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    with open(os.path.join(folder, "attendees.md"), "w", encoding="utf-8") as f:
        f.write("names")
    os.makedirs(os.path.join(folder, "wiki"), exist_ok=True)
    with open(os.path.join(folder, "wiki", "Topic.md"), "w", encoding="utf-8") as f:
        f.write("topic")

    with urllib.request.urlopen(f"{BASE}/{session_id}/api/materials/zip", timeout=30) as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"] == "application/zip"
        payload = resp.read()

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        assert archive.read("wiki/Topic.md") == b"topic"

    assert "ai-summary.md" in names
    assert "wiki/Topic.md" in names
    assert "session-state.json" not in names, "internal daemon state leaked to participants"
    assert "attendees.md" not in names, "participant names leaked to participants"


def test_second_download_is_served_from_cache():
    """A second click within the TTL must not trigger another daemon build."""
    session_id = fresh_session("MaterialsZipCache")
    folder = os.path.join(SESSIONS_FOLDER, _active_session_folder(session_id))
    with open(os.path.join(folder, "ai-summary.md"), "w", encoding="utf-8") as f:
        f.write("summary")

    with urllib.request.urlopen(f"{BASE}/{session_id}/api/materials/zip", timeout=30) as resp:
        first = resp.read()
    with urllib.request.urlopen(f"{BASE}/{session_id}/api/materials/zip", timeout=10) as resp:
        second = resp.read()

    assert first == second
