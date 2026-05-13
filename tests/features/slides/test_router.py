import base64
import json
import os

from fastapi.responses import JSONResponse, Response
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


# slides_current is daemon-resident state; the daemon broadcasts
# current_slide_updated to participants via WS. Railway no longer holds or
# exposes it, so there is no /api/status assertion here. Coverage lives in
# the hermetic tests (test_follow_me, test_follow_mode_slow_drive, slides
# bdd scenarios) which read window._hostSlidesCurrent on the participant page.


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

    # Download endpoint reads from uploaded slides dir directly (does not need daemon)
    public = TestClient(app)
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


# NOTE: GET /api/slides now proxies to daemon — local-file-listing tests removed.
# NOTE: state.slides removed from Railway state — daemon provides slide list via WS proxy.
# NOTE: /api/{session_id}/slides/catalog-map removed — catalog lives on daemon side.


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


def test_api_slides_check_proxies_to_daemon_with_participant_id():
    from unittest.mock import AsyncMock, patch

    mock_response = JSONResponse({"status": "cached"}, status_code=200)
    with patch("railway.features.slides.router.proxy_to_daemon", new_callable=AsyncMock, return_value=mock_response) as mock_proxy:
        client = TestClient(app)
        resp = client.get(
            f"/{state.session_id}/api/slides/check/demo",
            headers={"X-Participant-ID": "participant-123"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "cached"}
    mock_proxy.assert_awaited_once()
    kwargs = mock_proxy.await_args.kwargs
    assert kwargs["method"] == "GET"
    assert kwargs["path"] == f"/{state.session_id}/api/slides/check/demo"
    assert kwargs["participant_id"] == "participant-123"


def test_api_slides_check_propagates_non_200_status():
    from unittest.mock import AsyncMock, patch

    mock_response = JSONResponse({"status": "timeout"}, status_code=503)
    with patch("railway.features.slides.router.proxy_to_daemon", new_callable=AsyncMock, return_value=mock_response):
        client = TestClient(app)
        resp = client.get(f"/{state.session_id}/api/slides/check/demo")

    assert resp.status_code == 503
    assert resp.json() == {"status": "timeout"}


def test_api_slides_embeds_status_per_slide(monkeypatch):
    async def _fake_proxy(**_kwargs):
        return Response(
            content=json.dumps(
                {
                    "slides": [
                        {"slug": "reactive", "title": "Reactive/WebFlux", "drive_export_url": "https://example/export.pdf"},
                    ],
                    "cache_status": {
                        "reactive": {"status": "cached", "size_bytes": 1234},
                    },
                }
            ),
            status_code=200,
            media_type="application/json",
        )

    monkeypatch.setattr("railway.features.slides.router.proxy_to_daemon", _fake_proxy)
    client = TestClient(app)
    resp = client.get(f"/{state.session_id}/api/slides")
    assert resp.status_code == 200
    body = resp.json()
    assert "cache_status" not in body
    assert body["slides"][0]["slug"] == "reactive"
    assert body["slides"][0]["status"] == "cached"
    assert body["slides"][0]["size_bytes"] == 1234


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
