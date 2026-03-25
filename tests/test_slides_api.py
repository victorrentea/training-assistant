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


def test_api_slides_lists_local_materials_and_serves_pdf(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(tmp_path))
    pdf = tmp_path / "Architecture.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%test\n")

    client = TestClient(app)
    resp = client.get("/api/slides")
    assert resp.status_code == 200
    slides = resp.json()["slides"]
    assert len(slides) == 1
    assert slides[0]["name"] == "Architecture"
    assert slides[0]["url"].startswith("/api/slides/file/")

    file_resp = client.get(slides[0]["url"])
    assert file_resp.status_code == 200
    assert file_resp.headers.get("content-type", "").startswith("application/pdf")
    assert file_resp.content.startswith(b"%PDF-1.4")


def test_api_slides_merges_local_and_daemon_entries(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(tmp_path))
    (tmp_path / "Local Deck.pdf").write_bytes(b"%PDF-1.4\n%local\n")
    state.slides = [
        {
            "name": "Remote Deck",
            "slug": "remote-deck",
            "url": "https://slides.example.com/remote.pdf",
            "updated_at": "2026-03-25T20:30:00+00:00",
        }
    ]

    client = TestClient(app)
    resp = client.get("/api/slides")
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()["slides"]]
    assert "Local Deck" in names
    assert "Remote Deck" in names


def test_api_slides_includes_slides_current_when_present(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(tmp_path))
    state.slides_current = {
        "url": "https://slides.example.com/current.pdf",
        "slug": "current-123",
        "source_file": "Deck Live.pdf",
        "updated_at": "2026-03-25T20:40:00+00:00",
    }
    client = TestClient(app)
    resp = client.get("/api/slides")
    assert resp.status_code == 200
    slides = resp.json()["slides"]
    assert any(s["slug"] == "current-123" and s["url"] == "https://slides.example.com/current.pdf" for s in slides)
