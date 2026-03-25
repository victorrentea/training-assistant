import base64
import os

from fastapi.testclient import TestClient

from main import app, state


_HOST_AUTH_HEADERS = {
    "Authorization": "Basic " + base64.b64encode(
        f"{os.environ.get('HOST_USERNAME', 'host')}:{os.environ.get('HOST_PASSWORD', 'host')}".encode()
    ).decode()
}


def setup_function():
    state.reset()


def teardown_function():
    state.reset()


def test_slides_current_set_and_get_publicly():
    client = TestClient(app, headers=_HOST_AUTH_HEADERS)
    payload = {
        "url": "https://slides.example.com/abc123.pdf",
        "slug": "abc123",
        "source_file": "deck.pptx",
        "converter": "google_drive",
    }

    resp = client.post("/api/slides/current", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["slides_current"]["url"] == payload["url"]
    assert body["slides_current"]["slug"] == payload["slug"]
    assert body["slides_current"]["source_file"] == payload["source_file"]
    assert body["slides_current"]["converter"] == payload["converter"]
    assert body["slides_current"]["updated_at"]

    public = TestClient(app)
    get_resp = public.get("/api/slides/current")
    assert get_resp.status_code == 200
    assert get_resp.json()["slides_current"]["url"] == payload["url"]

    status = public.get("/api/status")
    assert status.status_code == 200
    assert status.json()["slides_current"]["slug"] == payload["slug"]

    snapshot = client.get("/api/state-snapshot")
    assert snapshot.status_code == 200
    assert snapshot.json()["state"]["slides_current"]["slug"] == payload["slug"]


def test_slides_current_requires_host_auth_for_write():
    client = TestClient(app)
    payload = {"url": "https://slides.example.com/x.pdf", "slug": "x"}
    resp = client.post("/api/slides/current", json=payload)
    assert resp.status_code in (401, 403)

    resp = client.delete("/api/slides/current")
    assert resp.status_code in (401, 403)
