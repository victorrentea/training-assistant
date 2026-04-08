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
    state.generate_session_id()


def teardown_function():
    state.reset()


def test_upload_download_endpoint_serves_temp_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    client = TestClient(app, headers=_HOST_AUTH_HEADERS)

    state.participant_names["p1"] = "Alice"
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
    state.participant_names["p1"] = "Alice"

    upload_resp = client.post(
        f"/{state.session_id}/api/upload",
        data={"uuid": "p1"},
        files={"file": ("apis.md", b"# hello\n", "text/markdown")},
    )
    assert upload_resp.status_code == 200
    file_id = upload_resp.json()["id"]

    unauth = client.get(f"/api/{state.session_id}/upload/{file_id}")
    assert unauth.status_code in (401, 403)
