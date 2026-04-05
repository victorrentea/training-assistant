import base64
import json
import os
import threading
from datetime import datetime, timezone

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


def test_slides_current_get_publicly():
    """GET /api/slides/current is public and returns slides_current from state."""
    state.slides_current = {
        "url": "https://slides.example.com/abc123.pdf",
        "slug": "abc123",
        "source_file": "deck.pptx",
        "presentation_name": "deck.pptx",
        "current_page": 3,
        "converter": "google_drive",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }

    public = TestClient(app)
    get_resp = public.get(f"/{state.session_id}/api/slides/current")
    assert get_resp.status_code == 200
    assert get_resp.json()["slides_current"]["url"] == state.slides_current["url"]

    status = public.get("/api/status")
    assert status.status_code == 200
    assert status.json()["slides_current"]["slug"] == "abc123"


# NOTE: POST /slides/current and DELETE /slides/current removed — daemon uses WS now.


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
    resp = public.get(f"/{state.session_id}/api/slides")
    assert resp.status_code == 200
    slides = resp.json()["slides"]
    assert any(s["slug"] == "demo-deck" and s["name"] == "Demo Deck" for s in slides)

    file_resp = public.get(f"/{state.session_id}/api/slides/download/demo-deck")
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
    monkeypatch.setenv("PPTX_CATALOG_FILE", str(tmp_path / "missing-catalog.json"))
    monkeypatch.setenv("TRAINING_ASSISTANT_UPLOADED_SLIDES_DIR", str(tmp_path / "uploaded"))
    pdf = tmp_path / "Architecture.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%test\n")

    client = TestClient(app)
    resp = client.get(f"/{state.session_id}/api/slides")
    assert resp.status_code == 200
    slides = resp.json()["slides"]
    assert len(slides) == 1
    assert slides[0]["name"] == "Architecture"
    assert slides[0]["url"].startswith(f"/{state.session_id}/api/slides/download/")

    file_resp = client.get(slides[0]["url"])
    assert file_resp.status_code == 200
    assert file_resp.headers.get("content-type", "").startswith("application/pdf")
    assert file_resp.headers.get("cache-control") == "no-cache"
    assert file_resp.headers.get("etag")
    assert file_resp.headers.get("last-modified")
    assert file_resp.content.startswith(b"%PDF-1.4")
    head_resp = client.head(slides[0]["url"])
    assert head_resp.status_code == 200
    assert head_resp.headers.get("content-type", "").startswith("application/pdf")
    assert head_resp.headers.get("cache-control") == "no-cache"
    assert head_resp.headers.get("etag") == file_resp.headers.get("etag")
    assert head_resp.headers.get("last-modified") == file_resp.headers.get("last-modified")

    not_modified = client.get(
        slides[0]["url"],
        headers={"If-None-Match": file_resp.headers["etag"]},
    )
    assert not_modified.status_code == 304


def test_api_slides_uses_publish_dir_when_local_dir_not_set(monkeypatch, tmp_path):
    monkeypatch.delenv("TRAINING_ASSISTANT_SLIDES_DIR", raising=False)
    monkeypatch.setenv("PPTX_PUBLISH_DIR", str(tmp_path))
    pdf = tmp_path / "FCA.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%test\n")

    client = TestClient(app)
    resp = client.get(f"/{state.session_id}/api/slides")
    assert resp.status_code == 200
    slides = resp.json()["slides"]
    assert any(s["slug"] == "fca" and s["name"] == "FCA" for s in slides)

    file_resp = client.get(f"/{state.session_id}/api/slides/download/fca")
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
    resp = client.get(f"/{state.session_id}/api/slides")
    assert resp.status_code == 200
    slides = resp.json()["slides"]
    assert any(s["slug"] == "fca" and s["name"] == "FCA" for s in slides)

    file_resp = client.get(f"/{state.session_id}/api/slides/download/fca")
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
    resp = client.get(f"/{state.session_id}/api/slides")
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
    resp = client.get(f"/{state.session_id}/api/slides")
    assert resp.status_code == 200
    slides = resp.json()["slides"]
    assert any(s["slug"] == "current-123" and s["url"] == f"/{state.session_id}/api/slides/download/current-123" for s in slides)


def test_api_slides_ignores_non_displayable_names(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(tmp_path))
    monkeypatch.setenv("PPTX_CATALOG_FILE", str(tmp_path / "missing-catalog.json"))
    monkeypatch.setenv("TRAINING_ASSISTANT_UPLOADED_SLIDES_DIR", str(tmp_path / "uploaded"))
    (tmp_path / "---.pdf").write_bytes(b"%PDF-1.4\n%local\n")
    state.slides = [
        {"name": "   ", "slug": "blank", "url": "https://slides.example.com/blank.pdf"},
        {"name": "---", "slug": "dashes", "url": "https://slides.example.com/dashes.pdf"},
        {"name": "Deck 1", "slug": "deck-1", "url": "https://slides.example.com/deck-1.pdf"},
    ]

    client = TestClient(app)
    resp = client.get(f"/{state.session_id}/api/slides")
    assert resp.status_code == 200
    slides = resp.json()["slides"]
    assert [s["name"] for s in slides] == ["Deck 1"]


def test_slides_catalog_map_requires_host_auth():
    client = TestClient(app)
    resp = client.get(f"/api/{state.session_id}/slides/catalog-map")
    assert resp.status_code in (401, 403)


# NOTE: /api/slides/participant-availability endpoint removed in Task 10 (drive_status.py cleanup)


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
    resp = client.get(f"/api/{state.session_id}/slides/catalog-map")
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


def test_api_slides_includes_catalog_entries_when_pdfs_missing(monkeypatch, tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({
        "decks": [
            {"title": "Performance Intro", "target_pdf": "Performance Introduction.pdf"},
            {"title": "Testing", "slug": "testing-101", "target_pdf": "Testing 101.pdf"},
        ]
    }), encoding="utf-8")
    monkeypatch.setenv("PPTX_CATALOG_FILE", str(catalog))
    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(tmp_path / "missing-slides"))
    monkeypatch.setenv("TRAINING_ASSISTANT_UPLOADED_SLIDES_DIR", str(tmp_path / "uploaded"))
    client = TestClient(app)
    resp = client.get(f"/{state.session_id}/api/slides")
    assert resp.status_code == 200
    slides = resp.json()["slides"]
    assert len(slides) == 2
    assert {s["slug"] for s in slides} == {"performance-introduction", "testing-101"}


def test_api_slides_includes_missing_local_slides_when_daemon_offline(monkeypatch, tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({
        "decks": [
            {"title": "Performance Intro", "target_pdf": "Performance Introduction.pdf"},
        ]
    }), encoding="utf-8")
    monkeypatch.setenv("PPTX_CATALOG_FILE", str(catalog))
    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(tmp_path / "missing-slides"))
    monkeypatch.setenv("TRAINING_ASSISTANT_UPLOADED_SLIDES_DIR", str(tmp_path / "uploaded"))

    client = TestClient(app)
    resp = client.get(f"/{state.session_id}/api/slides")
    assert resp.status_code == 200
    slides = resp.json()["slides"]
    assert len(slides) == 1
    assert slides[0]["slug"] == "performance-introduction"


def test_api_slides_returns_ok_when_daemon_offline(monkeypatch, tmp_path):
    # Railway proxies /api/slides to daemon; if daemon is offline, returns empty slides list
    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(tmp_path / "missing-slides"))
    monkeypatch.setenv("TRAINING_ASSISTANT_UPLOADED_SLIDES_DIR", str(tmp_path / "uploaded"))

    from unittest.mock import AsyncMock, MagicMock, patch
    mock_response = MagicMock()
    mock_response.status_code = 503
    with patch("railway.features.slides.router.proxy_to_daemon", new_callable=AsyncMock, return_value=mock_response):
        client = TestClient(app)
        resp = client.get(f"/{state.session_id}/api/slides")

    assert resp.status_code == 200
    body = resp.json()
    assert body["slides"] == []


def test_api_slides_respects_catalog_order_for_topics(monkeypatch, tmp_path):
    slides_dir = tmp_path / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)
    (slides_dir / "Architecture.pdf").write_bytes(b"%PDF-1.4\n%arch\n")
    (slides_dir / "Clean Code.pdf").write_bytes(b"%PDF-1.4\n%clean\n")

    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({
        "decks": [
            {"title": "Clean Code", "target_pdf": "Clean Code.pdf"},
            {"title": "Architecture", "target_pdf": "Architecture.pdf"},
        ]
    }), encoding="utf-8")

    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(slides_dir))
    monkeypatch.setenv("PPTX_CATALOG_FILE", str(catalog))

    client = TestClient(app)
    resp = client.get(f"/{state.session_id}/api/slides")
    assert resp.status_code == 200
    slides = resp.json()["slides"]
    assert [s["slug"] for s in slides[:2]] == ["clean-code", "architecture"]


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


def test_materials_upsert_slide_uses_source_mtime_for_updated_at(monkeypatch, tmp_path):
    target_dir = tmp_path / "server_materials"
    monkeypatch.setenv("SERVER_MATERIALS_DIR", str(target_dir))
    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(target_dir / "slides"))
    monkeypatch.chdir(tmp_path)
    client = TestClient(app, headers=_HOST_AUTH_HEADERS)

    source_mtime = 1700000000.0
    upsert = client.post(
        "/api/materials/upsert",
        data={"relative_path": "slides/Clean Code.pdf", "source_mtime": str(source_mtime)},
        files={"file": ("Clean Code.pdf", b"%PDF-1.4\n%mirror\n", "application/pdf")},
    )
    assert upsert.status_code == 200
    body = upsert.json()
    assert body["ok"] is True
    expected = datetime.fromtimestamp(source_mtime, tz=timezone.utc).isoformat()
    assert body["updated_at"] == expected

    slides = client.get(f"/{state.session_id}/api/slides").json()["slides"]
    clean = next(s for s in slides if s["slug"] == "clean-code")
    assert clean["updated_at"] == expected

    meta = tmp_path / ".server-data" / "local-slides-meta" / "clean-code.json"
    assert meta.exists()

    delete = client.post("/api/materials/delete", json={"relative_path": "slides/Clean Code.pdf"})
    assert delete.status_code == 200
    assert not meta.exists()


def test_materials_upsert_rejects_traversal(monkeypatch, tmp_path):
    monkeypatch.setenv("SERVER_MATERIALS_DIR", str(tmp_path / "server_materials"))
    client = TestClient(app, headers=_HOST_AUTH_HEADERS)

    resp = client.post(
        "/api/materials/upsert",
        data={"relative_path": "../escape.txt"},
        files={"file": ("escape.txt", b"bad", "text/plain")},
    )
    assert resp.status_code == 400


def test_api_slides_file_missing_returns_404_when_not_in_cache_or_catalog(monkeypatch, tmp_path):
    # New behavior: no daemon upload flow; missing slide returns 404
    slides_dir = tmp_path / "server_materials" / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(slides_dir))
    monkeypatch.setenv("SERVER_MATERIALS_DIR", str(tmp_path / "server_materials"))

    client = TestClient(app)
    resp = client.get(f"/{state.session_id}/api/slides/download/fca")
    assert resp.status_code == 404


def test_api_slides_file_served_from_cache_dir(monkeypatch, tmp_path):
    # New behavior: file found in cache dir (/tmp/slides-cache/{slug}.pdf) is served
    from railway.features.slides.cache import CACHE_DIR

    slides_dir = tmp_path / "server_materials" / "slides"
    slides_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(slides_dir))

    # Write a fake cached PDF
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached_pdf = CACHE_DIR / "fca.pdf"
    cached_pdf.write_bytes(b"%PDF-1.4\n%cached\n")

    try:
        client = TestClient(app)
        resp = client.get(f"/{state.session_id}/api/slides/download/fca")
        assert resp.status_code == 200
        assert resp.content.startswith(b"%PDF-1.4")
    finally:
        cached_pdf.unlink(missing_ok=True)


def test_api_slides_file_inline_query_sets_inline_disposition(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(tmp_path))
    pdf = tmp_path / "Inline.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%inline\n")

    client = TestClient(app)
    resp = client.get(f"/{state.session_id}/api/slides/download/inline?inline=1")
    assert resp.status_code == 200
    assert resp.headers.get("content-disposition", "").startswith('inline; filename="Inline.pdf"')


def test_api_slides_file_defaults_to_inline_and_supports_explicit_download(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(tmp_path))
    pdf = tmp_path / "Deck.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%deck\n")

    client = TestClient(app)
    inline_resp = client.get(f"/{state.session_id}/api/slides/download/deck")
    assert inline_resp.status_code == 200
    assert inline_resp.headers.get("content-disposition", "").startswith('inline; filename="Deck.pdf"')

    download_resp = client.get(f"/{state.session_id}/api/slides/download/deck?download=1")
    assert download_resp.status_code == 200
    assert download_resp.headers.get("content-disposition", "").startswith('attachment; filename="Deck.pdf"')


# NOTE: /api/slides/upload-status/{slug} endpoint removed in Task 10 (drive_status.py cleanup)

