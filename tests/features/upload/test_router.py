import base64
import os

from fastapi.testclient import TestClient

from railway.app import app, state

_HOST_AUTH_HEADERS = {
    "Authorization": "Basic " + base64.b64encode(
        f"{os.environ.get('HOST_USERNAME', 'host')}:{os.environ.get('HOST_PASSWORD', 'host')}".encode()
    ).decode()
}


def setup_function():
    state.reset()
    state.session_id = "e2etst"


def teardown_function():
    state.reset()


def test_upload_accepted_while_participant_websocket_is_down(monkeypatch, tmp_path):
    """A participant who joined this session may upload even with no live socket.

    Regression: the guard used to accept only uuids in ``state.participants``
    (the live-socket map), so every WS blip — phone waking up, network switch,
    daemon restart evicting clients — turned a legitimate upload into
    400 "Unknown participant". Membership is identity, not liveness.
    """
    monkeypatch.chdir(tmp_path)
    client = TestClient(app)

    state.participant_history.add("p1")  # joined earlier; socket since dropped
    assert "p1" not in state.participants

    resp = client.post(
        f"/{state.session_id}/api/upload",
        data={"uuid": "p1"},
        files={"file": ("notes.md", b"# hello\n", "text/markdown")},
    )
    assert resp.status_code == 200, resp.text


def test_upload_rejected_for_uuid_that_never_joined_this_session(monkeypatch, tmp_path):
    """A uuid unknown to this session (e.g. a previous cohort) cannot upload."""
    monkeypatch.chdir(tmp_path)
    client = TestClient(app)

    resp = client.post(
        f"/{state.session_id}/api/upload",
        data={"uuid": "stranger"},
        files={"file": ("notes.md", b"# hello\n", "text/markdown")},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Unknown participant"


def test_upload_download_endpoint_serves_temp_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    client = TestClient(app, headers=_HOST_AUTH_HEADERS)

    state.participant_history.add("p1")
    upload_resp = client.post(
        f"/{state.session_id}/api/upload",
        data={"uuid": "p1"},
        files={"file": ("apis.md", b"# hello\n", "text/markdown")},
    )
    assert upload_resp.status_code == 200
    file_id = upload_resp.json()["id"]

    download_resp = client.get(f"/api/{state.session_id}/upload/{file_id}")
    assert download_resp.status_code == 200
    assert download_resp.content == b"# hello\n"
    assert "apis.md" in (download_resp.headers.get("content-disposition") or "")


def test_upload_download_endpoint_requires_host_auth(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    client = TestClient(app)
    state.participant_history.add("p1")

    upload_resp = client.post(
        f"/{state.session_id}/api/upload",
        data={"uuid": "p1"},
        files={"file": ("apis.md", b"# hello\n", "text/markdown")},
    )
    assert upload_resp.status_code == 200
    file_id = upload_resp.json()["id"]

    unauth = client.get(f"/api/{state.session_id}/upload/{file_id}")
    assert unauth.status_code in (401, 403)
