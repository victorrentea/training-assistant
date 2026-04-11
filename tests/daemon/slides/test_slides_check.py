"""Unit tests for daemon slides /check endpoint (daemon/slides/router.py).

The /check endpoint now calls Railway REST POST /api/slides/download-from-gdrive/{slug}
instead of using WS download_pdf + pdf_download_complete.
"""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from daemon.misc.state import MiscState
from daemon.slides.router import participant_router


@pytest.fixture
def fresh_misc_state():
    """Provide a clean MiscState for each test."""
    ms = MiscState()
    with patch("daemon.slides.router.misc_state", ms):
        yield ms


@pytest.fixture
def client(fresh_misc_state):
    """TestClient with participant slides router mounted."""
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app, raise_server_exceptions=False)


def test_check_returns_200_when_cached(client, fresh_misc_state):
    """When cache status is cached, /check returns 200 immediately (trusts daemon state)."""
    fresh_misc_state.slides_cache_status["myslug"] = {"status": "cached"}

    resp = client.get("/test-session/api/slides/check/myslug")

    assert resp.status_code == 200
    assert resp.json()["status"] == "cached"


def test_list_slides_embeds_cache_status(client, fresh_misc_state):
    fresh_misc_state.slides_catalog = {
        "reactive": {
            "slug": "reactive",
            "title": "Reactive/WebFlux",
            "drive_export_url": "https://docs.google.com/presentation/d/abc/export/pdf",
        }
    }
    fresh_misc_state.slides_cache_status["reactive"] = {"status": "cached", "size_bytes": 42}

    resp = client.get("/test-session/api/slides")
    assert resp.status_code == 200
    body = resp.json()
    assert "cache_status" not in body
    assert body["slides"][0]["slug"] == "reactive"
    assert body["slides"][0]["status"] == "cached"
    assert body["slides"][0]["size_bytes"] == 42


def test_check_calls_railway_rest_and_returns_200(fresh_misc_state, monkeypatch):
    """Not cached: calls Railway REST to download, returns 200 on success."""
    fresh_misc_state.slides_catalog["myslug"] = {
        "slug": "myslug",
        "title": "My Slide",
        "drive_export_url": "https://docs.google.com/presentation/d/xyz/export/pdf",
    }

    def fake_download_on_railway(slug, drive_export_url):
        return {"status": "cached", "sha256": "abc123", "size": 1024}

    monkeypatch.setattr("daemon.slides.router.download_on_railway", fake_download_on_railway)

    broadcasts = []

    def _capture_broadcast(msg):
        broadcasts.append(msg)

    with patch("daemon.ws_publish.broadcast", side_effect=_capture_broadcast):
        app = FastAPI()
        app.include_router(participant_router)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-session/api/slides/check/myslug")

    assert resp.status_code == 200
    assert resp.json()["status"] == "cached"
    assert fresh_misc_state.slides_cache_status["myslug"]["status"] == "cached"
    assert fresh_misc_state.slides_cache_status["myslug"]["last_sha256"] == "abc123"
    assert len(broadcasts) >= 2  # downloading + cached


def test_check_returns_503_on_railway_failure(fresh_misc_state, monkeypatch):
    """Railway download failure → 503."""
    fresh_misc_state.slides_catalog["myslug"] = {
        "slug": "myslug",
        "title": "My Slide",
        "drive_export_url": "https://docs.google.com/presentation/d/xyz/export/pdf",
    }

    def fake_download_on_railway(slug, drive_export_url):
        raise RuntimeError("Connection refused")

    monkeypatch.setattr("daemon.slides.router.download_on_railway", fake_download_on_railway)

    with patch("daemon.ws_publish.broadcast"):
        app = FastAPI()
        app.include_router(participant_router)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/test-session/api/slides/check/myslug")

    assert resp.status_code == 503
    assert fresh_misc_state.slides_cache_status["myslug"]["status"] == "download_failed"


def test_check_returns_404_when_no_drive_url(client, fresh_misc_state):
    """No drive_export_url in catalog → 404."""
    fresh_misc_state.slides_catalog["myslug"] = {
        "slug": "myslug",
        "title": "My Slide",
    }
    resp = client.get("/test-session/api/slides/check/myslug")
    assert resp.status_code == 404
