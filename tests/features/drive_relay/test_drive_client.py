import http.client
import io
import json
import urllib.error

import pytest

from railway.features.drive_relay import drive_client as dc


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class RaisingResponse(io.BytesIO):
    """A fake response whose `.read()` yields a few chunks, then raises.

    Models a connection that dies mid-body: the socket accepted the request
    and started sending bytes (or sent none at all), then broke.
    """

    def __init__(self, chunks, exc):
        super().__init__(b"")
        self._chunks = list(chunks)
        self._exc = exc

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        if self._chunks:
            return self._chunks.pop(0)
        raise self._exc


@pytest.fixture(autouse=True)
def api_config(monkeypatch):
    monkeypatch.setenv("GOOGLE_DRIVE_API_KEY", "test-key")
    monkeypatch.setenv("DRIVE_API_BASE_URL", "https://drive.test/drive/v3")


def install_urlopen(monkeypatch, handler):
    """Route every urlopen call through `handler(url) -> bytes`, recording URLs."""
    calls = []

    def fake_urlopen(request, **kwargs):
        url = request.full_url
        calls.append(url)
        return FakeResponse(handler(url))

    monkeypatch.setattr(dc.urllib.request, "urlopen", fake_urlopen)
    return calls


def install_urlopen_response(monkeypatch, response_factory):
    """Route every urlopen call to a response object built by `response_factory(url)`.

    Unlike `install_urlopen`, this hands back the response object itself rather
    than always wrapping plain bytes — needed for `RaisingResponse`, where the
    failure has to happen inside `.read()`, not while urlopen() connects.
    """
    calls = []

    def fake_urlopen(request, **kwargs):
        url = request.full_url
        calls.append(url)
        return response_factory(url)

    monkeypatch.setattr(dc.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_get_metadata_calls_the_right_url(monkeypatch):
    payload = {"id": "abc", "name": "Materials", "mimeType": dc.FOLDER_MIME}
    calls = install_urlopen(monkeypatch, lambda url: json.dumps(payload).encode())

    dc.get_metadata("abc")

    assert calls[0].startswith("https://drive.test/drive/v3/files/abc?")
    assert "key=test-key" in calls[0]
    assert "owners%28emailAddress%2CpermissionId%2CdisplayName%29" in calls[0]


def test_get_metadata_parses_owners_and_size(monkeypatch):
    payload = {
        "id": "abc", "name": "Slides.pdf", "mimeType": "application/pdf", "size": "1234",
        "owners": [{"emailAddress": "v@example.com", "permissionId": "42",
                    "displayName": "Victor"}],
    }
    install_urlopen(monkeypatch, lambda url: json.dumps(payload).encode())

    file = dc.get_metadata("abc")

    assert file.id == "abc"
    assert file.name == "Slides.pdf"
    assert file.size == 1234
    assert file.owners[0].email == "v@example.com"
    assert file.owners[0].permission_id == "42"
    assert file.shortcut_target_id is None


def test_native_files_have_no_size(monkeypatch):
    payload = {"id": "d1", "name": "Notes", "mimeType": "application/vnd.google-apps.document"}
    install_urlopen(monkeypatch, lambda url: json.dumps(payload).encode())

    file = dc.get_metadata("d1")

    assert file.size is None
    assert dc.is_native(file) is True
    assert dc.archive_name(file) == "Notes.pdf"


def test_archive_name_leaves_binary_names_alone(monkeypatch):
    payload = {"id": "f1", "name": "Deck.pdf", "mimeType": "application/pdf", "size": "10"}
    install_urlopen(monkeypatch, lambda url: json.dumps(payload).encode())

    assert dc.archive_name(dc.get_metadata("f1")) == "Deck.pdf"


def test_list_children_follows_pagination(monkeypatch):
    pages = {
        1: {"files": [{"id": "a", "name": "A", "mimeType": "application/pdf", "size": "1"}],
            "nextPageToken": "TOKEN2"},
        2: {"files": [{"id": "b", "name": "B", "mimeType": "application/pdf", "size": "2"}]},
    }

    def handler(url):
        page = 2 if "pageToken=TOKEN2" in url else 1
        return json.dumps(pages[page]).encode()

    calls = install_urlopen(monkeypatch, handler)

    children = dc.list_children("folder1")

    assert [c.id for c in children] == ["a", "b"]
    assert len(calls) == 2
    assert "trashed" in calls[0]  # trashed items excluded at the query level


def test_http_error_becomes_drive_error_with_status(monkeypatch):
    def fake_urlopen(request, **kwargs):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(dc.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(dc.DriveError) as exc:
        dc.get_metadata("missing")
    assert exc.value.status == 404


def test_network_failure_becomes_502(monkeypatch):
    def fake_urlopen(request, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(dc.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(dc.DriveError) as exc:
        dc.get_metadata("abc")
    assert exc.value.status == 502


def test_missing_api_key_is_a_clear_failure(monkeypatch):
    monkeypatch.delenv("GOOGLE_DRIVE_API_KEY", raising=False)

    with pytest.raises(dc.DriveError) as exc:
        dc.get_metadata("abc")
    assert exc.value.status == 503


def test_binary_download_streams_chunks(monkeypatch):
    body = b"y" * (dc._CHUNK_BYTES + 7)
    urls = install_urlopen(monkeypatch, lambda url: body)
    file = dc.DriveFile(id="f1", name="a.bin", mime_type="application/octet-stream",
                        size=len(body), owners=(), shortcut_target_id=None)

    chunks = list(dc.open_download(file))

    assert b"".join(chunks) == body
    assert len(chunks) == 2
    assert "alt=media" in urls[0]


def test_native_download_uses_the_pdf_export_endpoint(monkeypatch):
    urls = install_urlopen(monkeypatch, lambda url: b"%PDF-1.4")
    file = dc.DriveFile(id="d1", name="Notes",
                        mime_type="application/vnd.google-apps.document",
                        size=None, owners=(), shortcut_target_id=None)

    assert b"".join(dc.open_download(file)) == b"%PDF-1.4"
    assert "/files/d1/export" in urls[0]
    assert "mimeType=application%2Fpdf" in urls[0]


def test_body_read_failure_becomes_502(monkeypatch):
    """A connection that drops while reading the metadata body is still a DriveError."""
    install_urlopen_response(
        monkeypatch,
        lambda url: RaisingResponse([], http.client.IncompleteRead(b"partial")),
    )

    with pytest.raises(dc.DriveError) as exc:
        dc.get_metadata("abc")
    assert exc.value.status == 502


def test_streaming_read_failure_becomes_502(monkeypatch):
    """A connection that drops mid-download must not escape as IncompleteRead."""
    install_urlopen_response(
        monkeypatch,
        lambda url: RaisingResponse([b"first-chunk"], http.client.IncompleteRead(b"")),
    )
    file = dc.DriveFile(id="f1", name="a.bin", mime_type="application/octet-stream",
                        size=100, owners=(), shortcut_target_id=None)

    with pytest.raises(dc.DriveError) as exc:
        list(dc.open_download(file))
    assert exc.value.status == 502


def test_malformed_json_becomes_502(monkeypatch):
    install_urlopen(monkeypatch, lambda url: b"{not valid json")

    with pytest.raises(dc.DriveError) as exc:
        dc.get_metadata("abc")
    assert exc.value.status == 502
