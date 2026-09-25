import base64
import io
import os
import zipfile

import pytest
from fastapi.testclient import TestClient

from railway.app import app, state
from railway.features.wiki import router as wiki

_HOST_AUTH_HEADERS = {
    "Authorization": "Basic " + base64.b64encode(
        f"{os.environ.get('HOST_USERNAME', 'host')}:{os.environ.get('HOST_PASSWORD', 'host')}".encode()
    ).decode()
}


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


SITE = _zip({
    "index.html": "<h1>Home</h1>",
    "Chat-Memory.html": "<h1>Chat Memory</h1>",
    "tags/index.html": "<h1>Tags</h1>",
    "static/contentIndex.json": "{}",
    "404.html": "<h1>Lost</h1>",
})


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(wiki, "WIKI_DIR", tmp_path / "wiki")
    state.reset()
    state.session_id = "e2etst"
    yield
    state.reset()


def _upload(client, session_id="e2etst", payload=SITE, auth=True):
    return client.post(
        "/api/wiki/upload",
        data={"session_id": session_id},
        files={"file": ("wiki.zip", payload, "application/zip")},
        headers=_HOST_AUTH_HEADERS if auth else {},
    )


def test_upload_requires_host_auth():
    with TestClient(app) as client:
        assert _upload(client, auth=False).status_code == 401


def test_serves_quartz_clean_urls():
    with TestClient(app) as client:
        assert _upload(client).json() == {"ok": True, "files": 5}
        assert client.get("/e2etst/wiki-site/").text == "<h1>Home</h1>"
        assert client.get("/e2etst/wiki-site/Chat-Memory").text == "<h1>Chat Memory</h1>"
        assert client.get("/e2etst/wiki-site/tags/").text == "<h1>Tags</h1>"
        assert client.get("/e2etst/wiki-site/static/contentIndex.json").json() == {}


def test_unknown_page_gets_the_sites_own_404():
    with TestClient(app) as client:
        _upload(client)
        response = client.get("/e2etst/wiki-site/Nope")
    assert response.status_code == 404
    assert response.text == "<h1>Lost</h1>"


def test_nothing_published_is_404():
    with TestClient(app) as client:
        assert client.get("/e2etst/wiki-site/").status_code == 404


def test_only_the_active_session_is_served():
    """A past session's wiki must never be reachable, even by its own old link."""
    with TestClient(app) as client:
        _upload(client)
        state.session_id = "newses"
        assert client.get("/e2etst/wiki-site/").status_code == 404


def test_publishing_a_session_deletes_every_other_sessions_site(tmp_path):
    with TestClient(app) as client:
        _upload(client, session_id="oldses")
        _upload(client, session_id="e2etst")
    assert sorted(p.name for p in (tmp_path / "wiki").iterdir()) == ["e2etst"]


def test_republish_replaces_the_site():
    with TestClient(app) as client:
        _upload(client)
        _upload(client, payload=_zip({"index.html": "v2"}))
        assert client.get("/e2etst/wiki-site/").text == "v2"
        assert client.get("/e2etst/wiki-site/Chat-Memory").status_code == 404


@pytest.mark.parametrize("name", ["../escape.html", "/abs.html", "a/../../escape.html"])
def test_zip_slip_is_rejected(name, tmp_path):
    with TestClient(app) as client:
        response = _upload(client, payload=_zip({name: "x"}))
    assert response.status_code == 400
    assert not (tmp_path / "escape.html").exists()


def test_path_traversal_in_url_is_404():
    with TestClient(app) as client:
        _upload(client)
        assert client.get("/e2etst/wiki-site/..%2F..%2Fsecrets.env").status_code == 404


def test_non_alphanumeric_session_id_is_rejected():
    with TestClient(app) as client:
        assert _upload(client, session_id="../x").status_code == 422
