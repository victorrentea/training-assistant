import base64
import json
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


def test_slides_upload_requires_host_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAINING_ASSISTANT_UPLOADED_SLIDES_DIR", str(tmp_path / "uploaded"))
    client = TestClient(app)
    resp = client.post(
        "/api/slides/upload",
        data={"slug": "demo", "name": "Demo"},
        files={"file": ("demo.pdf", b"%PDF-1.4\n%test\n", "application/pdf")},
    )
    assert resp.status_code in (401, 403)


def test_slides_upload_is_listed_and_served(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAINING_ASSISTANT_UPLOADED_SLIDES_DIR", str(tmp_path / "uploaded"))
    client = TestClient(app, headers=_HOST_AUTH_HEADERS)

    upload = client.post(
        "/api/slides/upload",
        data={"slug": "demo-deck", "name": "Demo Deck"},
        files={"file": ("demo.pdf", b"%PDF-1.4\n%test\n", "application/pdf")},
    )
    assert upload.status_code == 200
    body = upload.json()
    assert body["ok"] is True
    assert body["slide"]["slug"] == "demo-deck"

    public = TestClient(app)
    resp = public.get("/api/slides")
    assert resp.status_code == 200
    slides = resp.json()["slides"]
    assert any(s["slug"] == "demo-deck" and s["name"] == "Demo Deck" for s in slides)

    file_resp = public.get("/api/slides/file/demo-deck")
    assert file_resp.status_code == 200
    assert file_resp.content.startswith(b"%PDF-1.4")


def test_slides_upload_defaults_to_server_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("TRAINING_ASSISTANT_UPLOADED_SLIDES_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    client = TestClient(app, headers=_HOST_AUTH_HEADERS)

    upload = client.post(
        "/api/slides/upload",
        data={"slug": "fca", "name": "FCA"},
        files={"file": ("fca.pdf", b"%PDF-1.4\n%test\n", "application/pdf")},
    )
    assert upload.status_code == 200

    expected = tmp_path / ".server-data" / "uploaded-slides" / "fca.pdf"
    assert expected.exists()


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


def test_api_slides_uses_publish_dir_when_local_dir_not_set(monkeypatch, tmp_path):
    monkeypatch.delenv("TRAINING_ASSISTANT_SLIDES_DIR", raising=False)
    monkeypatch.setenv("PPTX_PUBLISH_DIR", str(tmp_path))
    pdf = tmp_path / "FCA.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%test\n")

    client = TestClient(app)
    resp = client.get("/api/slides")
    assert resp.status_code == 200
    slides = resp.json()["slides"]
    assert any(s["slug"] == "fca" and s["name"] == "FCA" for s in slides)

    file_resp = client.get("/api/slides/file/fca")
    assert file_resp.status_code == 200
    assert file_resp.headers.get("content-type", "").startswith("application/pdf")
    assert file_resp.content.startswith(b"%PDF-1.4")


def test_api_slides_defaults_to_server_materials_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("TRAINING_ASSISTANT_SLIDES_DIR", raising=False)
    monkeypatch.delenv("PPTX_PUBLISH_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    default_dir = tmp_path / "server_materials" / "slides"
    default_dir.mkdir(parents=True, exist_ok=True)
    pdf = default_dir / "FCA.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%test\n")

    client = TestClient(app)
    resp = client.get("/api/slides")
    assert resp.status_code == 200
    slides = resp.json()["slides"]
    assert any(s["slug"] == "fca" and s["name"] == "FCA" for s in slides)

    file_resp = client.get("/api/slides/file/fca")
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


def test_api_slides_ignores_non_displayable_names(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(tmp_path))
    (tmp_path / "---.pdf").write_bytes(b"%PDF-1.4\n%local\n")
    state.slides = [
        {"name": "   ", "slug": "blank", "url": "https://slides.example.com/blank.pdf"},
        {"name": "---", "slug": "dashes", "url": "https://slides.example.com/dashes.pdf"},
        {"name": "Deck 1", "slug": "deck-1", "url": "https://slides.example.com/deck-1.pdf"},
    ]

    client = TestClient(app)
    resp = client.get("/api/slides")
    assert resp.status_code == 200
    slides = resp.json()["slides"]
    assert [s["name"] for s in slides] == ["Deck 1"]


def test_slides_catalog_map_requires_host_auth():
    client = TestClient(app)
    resp = client.get("/api/slides/catalog-map")
    assert resp.status_code in (401, 403)


def test_slides_catalog_map_returns_pdf_to_pptx_entries(monkeypatch, tmp_path):
    source_ok = tmp_path / "Clean Code.pptx"
    source_ok.write_bytes(b"pptx")
    source_missing = tmp_path / "Missing.pptx"
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({
        "slides": [
            {"source": str(source_ok), "target_pdf": "Clean Code.pdf"},
            {"source": str(source_missing), "target_pdf": "Missing.pdf"},
        ]
    }), encoding="utf-8")
    monkeypatch.setenv("PPTX_CATALOG_FILE", str(catalog))

    client = TestClient(app, headers=_HOST_AUTH_HEADERS)
    resp = client.get("/api/slides/catalog-map")
    assert resp.status_code == 200
    body = resp.json()
    assert body["catalog_file"] == str(catalog)
    entries = body["entries"]
    assert len(entries) == 2

    clean = next(e for e in entries if e["pdf"] == "Clean Code.pdf")
    missing = next(e for e in entries if e["pdf"] == "Missing.pdf")
    assert clean["pptx_path"] == str(source_ok)
    assert clean["exists"] is True
    assert clean["updated_at"]
    assert missing["pptx_path"] == str(source_missing)
    assert missing["exists"] is False


def test_materials_upsert_and_delete_roundtrip(monkeypatch, tmp_path):
    target_dir = tmp_path / "server_materials"
    monkeypatch.setenv("SERVER_MATERIALS_DIR", str(target_dir))
    client = TestClient(app, headers=_HOST_AUTH_HEADERS)

    upsert = client.post(
        "/api/materials/upsert",
        data={"relative_path": "slides/AI Coding.pdf"},
        files={"file": ("AI Coding.pdf", b"%PDF-1.4\n%mirror\n", "application/pdf")},
    )
    assert upsert.status_code == 200
    assert upsert.json()["ok"] is True

    mirrored = target_dir / "slides" / "AI Coding.pdf"
    assert mirrored.exists()
    assert mirrored.read_bytes().startswith(b"%PDF-1.4")

    delete = client.post("/api/materials/delete", json={"relative_path": "slides/AI Coding.pdf"})
    assert delete.status_code == 200
    assert delete.json()["ok"] is True
    assert delete.json()["deleted"] is True
    assert not mirrored.exists()


def test_materials_upsert_rejects_traversal(monkeypatch, tmp_path):
    monkeypatch.setenv("SERVER_MATERIALS_DIR", str(tmp_path / "server_materials"))
    client = TestClient(app, headers=_HOST_AUTH_HEADERS)

    resp = client.post(
        "/api/materials/upsert",
        data={"relative_path": "../escape.txt"},
        files={"file": ("escape.txt", b"bad", "text/plain")},
    )
    assert resp.status_code == 400
