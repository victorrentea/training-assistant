import base64
import json
import os

import pytest
from fastapi.testclient import TestClient

from main import app, state
from features.ws.router import _handle_session_folders


_HOST_AUTH_HEADERS = {
    "Authorization": "Basic " + base64.b64encode(
        f"{os.environ.get('HOST_USERNAME', 'host')}:{os.environ.get('HOST_PASSWORD', 'host')}".encode()
    ).decode()
}


def setup_function():
    state.reset()


def teardown_function():
    state.reset()


def test_create_session_reuses_existing_folder_session_id():
    client = TestClient(app, headers=_HOST_AUTH_HEADERS)
    state.session_folder_ids["2026-03-30 Demo"] = "abc123"

    resp = client.post(
        "/api/session/create",
        json={"name": "2026-03-30 Demo", "type": "workshop"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "abc123"
    assert state.session_id == "abc123"


def test_resume_folder_assigns_session_id_once_when_missing():
    client = TestClient(app, headers=_HOST_AUTH_HEADERS)
    folder = "2026-02-01 Legacy Session"

    first = client.post("/api/session/resume-folder", json={"folder_name": folder})
    assert first.status_code == 200
    sid1 = first.json()["session_id"]
    assert isinstance(sid1, str) and len(sid1) == 6

    # Simulate later resume with no active session in memory.
    state.session_id = None

    second = client.post("/api/session/resume-folder", json={"folder_name": folder})
    assert second.status_code == 200
    sid2 = second.json()["session_id"]

    assert sid2 == sid1
    assert state.session_folder_ids[folder] == sid1


def test_resume_folder_uses_session_id_from_local_snapshot(monkeypatch, tmp_path):
    client = TestClient(app, headers=_HOST_AUTH_HEADERS)

    folder = "2026-01-15 Historical Session"
    folder_path = tmp_path / folder
    folder_path.mkdir(parents=True)
    (folder_path / "session_state.json").write_text(
        json.dumps({"session_id": "hist42", "session_name": folder}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SESSIONS_FOLDER", str(tmp_path))

    resp = client.post("/api/session/resume-folder", json={"folder_name": folder})
    assert resp.status_code == 200
    body = resp.json()

    assert body["session_id"] == "hist42"
    assert state.session_folder_ids[folder] == "hist42"


def test_session_active_autojoin_when_main_open_and_session_id_missing():
    client = TestClient(app, headers=_HOST_AUTH_HEADERS)
    state.session_main = {
        "name": "2026-03-29 Open Session",
        "started_at": "2026-03-29T09:00:00",
        "status": "active",
    }
    state.session_name = "2026-03-29 Open Session"
    state.session_id = None

    resp = client.get("/api/session/active")
    assert resp.status_code == 200
    body = resp.json()

    assert body["active"] is True
    assert body["auto_join"] is True
    assert isinstance(body["session_id"], str) and len(body["session_id"]) == 6
    assert state.session_folder_ids["2026-03-29 Open Session"] == body["session_id"]


def test_session_active_not_active_for_stopped_main_with_stale_session_id():
    client = TestClient(app, headers=_HOST_AUTH_HEADERS)
    state.session_main = {
        "name": "2026-03-29 Stopped Session",
        "started_at": "2026-03-29T09:00:00",
        "status": "ended",
    }
    state.session_id = "stale1"
    state.session_request = None

    resp = client.get("/api/session/active")
    assert resp.status_code == 200
    body = resp.json()

    assert body["active"] is False
    assert body["auto_join"] is False
    assert body["session_id"] == "stale1"


def test_session_active_pending_create_without_main_is_active_but_not_autojoin():
    client = TestClient(app, headers=_HOST_AUTH_HEADERS)
    state.session_main = None
    state.session_id = "abc123"
    state.session_request = {"action": "create", "name": "2026-03-29 Pending"}

    resp = client.get("/api/session/active")
    assert resp.status_code == 200
    body = resp.json()

    assert body["active"] is True
    assert body["auto_join"] is False
    assert body["session_id"] == "abc123"


@pytest.mark.anyio
async def test_ws_session_folders_updates_folder_to_id_map():
    await _handle_session_folders(
        {
            "folders": [
                {"name": "A", "session_id": "aaa111"},
                {"name": "B", "session_id": ""},
                "legacy-folder",
            ]
        }
    )

    assert state.session_folders == ["A", "B", "legacy-folder"]
    assert state.session_folder_ids == {"A": "aaa111"}
