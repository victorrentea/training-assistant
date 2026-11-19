"""The deck as PowerPoint prints it, sent by the daemon whole or page by page
(railway/features/slides/pages.py and its two routes)."""
import base64
import hashlib
import io
import json
import os

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from railway.app import app, state
from railway.features.slides import cache

_HOST_AUTH_HEADERS = {
    "Authorization": "Basic " + base64.b64encode(
        f"{os.environ.get('HOST_USERNAME', 'host')}:{os.environ.get('HOST_PASSWORD', 'host')}".encode()
    ).decode()
}


def _pdf(widths: list[int]) -> bytes:
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=100)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _widths(data: bytes) -> list[int]:
    return [round(float(p.mediabox.width)) for p in PdfReader(io.BytesIO(data)).pages]


@pytest.fixture
def client(tmp_path, monkeypatch):
    state.reset()
    state.session_id = "e2etst"
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "slides-cache")
    yield TestClient(app, headers=_HOST_AUTH_HEADERS)
    state.reset()


def _send_deck(client, widths) -> str:
    response = client.post("/api/slides/deck/demo", files={"file": ("deck.pdf", _pdf(widths), "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()["sha256"]


def test_both_routes_are_the_daemons_only():
    anonymous = TestClient(app)
    files = {"file": ("deck.pdf", _pdf([100]), "application/pdf")}
    assert anonymous.post("/api/slides/deck/demo", files=files).status_code in (401, 403)
    assert anonymous.post("/api/slides/pages/demo", files=files,
                          data={"base_sha256": "x", "positions": "[1]"}).status_code in (401, 403)


def test_whole_deck_replaces_what_is_cached(client):
    deck = _pdf([101, 102, 103])
    response = client.post("/api/slides/deck/demo", files={"file": ("deck.pdf", deck, "application/pdf")})

    assert response.json() == {"status": "cached", "sha256": hashlib.sha256(deck).hexdigest(), "size": len(deck), "pages": 0}
    assert cache._cache_path("demo").read_bytes() == deck
    assert state.slides_updated["demo"]["status"] == "cached"
    assert client.post("/api/slides/deck/demo", files={"file": ("x.pdf", b"not a pdf", "application/pdf")}).status_code == 400


def test_changed_pages_go_into_the_cached_deck(client):
    sha = _send_deck(client, [101, 102, 103, 104])

    response = client.post(
        "/api/slides/pages/demo",
        data={"base_sha256": sha, "positions": json.dumps([2, 4])},
        files={"file": ("pages.pdf", _pdf([902, 904]), "application/pdf")},
    )

    assert response.status_code == 200, response.text
    merged = cache._cache_path("demo").read_bytes()
    assert _widths(merged) == [101, 902, 103, 904]
    assert response.json()["sha256"] == hashlib.sha256(merged).hexdigest()
    assert response.json()["pages"] == 2


def test_pages_for_another_deck_are_refused(client):
    """After a restart, or with Google Drive's conversion in the cache: the daemon must
    send the whole deck, not patch a deck it does not know."""
    pages = {"file": ("pages.pdf", _pdf([902]), "application/pdf")}
    assert client.post("/api/slides/pages/demo", data={"base_sha256": "x", "positions": "[1]"}, files=pages).status_code == 409

    sha = _send_deck(client, [101, 102])
    assert client.post("/api/slides/pages/demo", data={"base_sha256": "other", "positions": "[1]"}, files=pages).status_code == 409
    for positions in ("[3]", "[1, 2]", '"1"', "[1, 1]"):
        refused = client.post("/api/slides/pages/demo", data={"base_sha256": sha, "positions": positions}, files=pages)
        assert refused.status_code == 422, positions
    assert _widths(cache._cache_path("demo").read_bytes()) == [101, 102]
