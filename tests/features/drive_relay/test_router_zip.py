import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from railway.app import app
from railway.features.drive_relay import router as relay
from railway.features.drive_relay.drive_client import FOLDER_MIME, DriveFile, DriveOwner
from railway.shared import rate_limit

FOLDER_ID = "1A2b3C4d5E6f7G8h9I0jKlMnOpQrStUv"
FOLDER_URL = f"https://drive.google.com/drive/folders/{FOLDER_ID}"

client = TestClient(app)


def owned_folder(name="Workshop Materials"):
    return DriveFile(
        id=FOLDER_ID, name=name, mime_type=FOLDER_MIME, size=None,
        owners=(DriveOwner(email="victorrentea@gmail.com", permission_id="1", display_name="V"),),
        shortcut_target_id=None,
    )


def pdf(id, name, size):
    return DriveFile(id=id, name=name, mime_type="application/pdf", size=size, owners=(),
                     shortcut_target_id=None)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("DRIVE_OWNER_EMAILS", "victorrentea@gmail.com")
    monkeypatch.setenv("GOOGLE_DRIVE_API_KEY", "test-key")
    monkeypatch.setenv("GATEWAY_RATE_LIMIT_DISABLED", "1")
    rate_limit.drive_zip_limiter.reset()


@pytest.fixture
def drive(monkeypatch):
    state = {"root": owned_folder(), "children": {}, "bodies": {}}
    monkeypatch.setattr(relay.drive_client, "get_metadata", lambda fid: state["root"])
    monkeypatch.setattr(relay.tree.drive_client, "get_metadata", lambda fid: state["root"])
    monkeypatch.setattr(relay.tree.drive_client, "list_children",
                        lambda fid: state["children"].get(fid, []))
    monkeypatch.setattr(relay.drive_client, "open_download",
                        lambda file: iter([state["bodies"].get(file.id, b"")]))
    return state


def test_zip_contains_every_file(drive):
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 5), pdf("b", "Lab.pdf", 3)]
    drive["bodies"] = {"a": b"INTRO", "b": b"LAB"}

    response = client.get("/api/drive/zip", params={"url": FOLDER_URL})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert archive.namelist() == ["Intro.pdf", "Lab.pdf"]
    assert archive.read("Intro.pdf") == b"INTRO"


def test_zip_is_named_after_the_folder(drive):
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 5)]
    drive["bodies"] = {"a": b"INTRO"}

    disposition = client.get("/api/drive/zip", params={"url": FOLDER_URL}).headers[
        "content-disposition"
    ]

    assert "Workshop Materials.zip" in disposition


def test_unicode_folder_names_survive_the_header(drive, monkeypatch):
    monkeypatch.setattr(relay.drive_client, "get_metadata", lambda fid: owned_folder("Curs Programare"))
    monkeypatch.setattr(relay.tree.drive_client, "get_metadata", lambda fid: owned_folder("Curs Programare"))
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 5)]
    drive["bodies"] = {"a": b"INTRO"}

    disposition = client.get("/api/drive/zip", params={"url": FOLDER_URL}).headers[
        "content-disposition"
    ]

    assert "filename*=UTF-8''" in disposition


def test_hostile_folder_name_produces_a_well_formed_header(drive, monkeypatch):
    """A Drive folder name can legitimately contain a slash, a quote or a raw
    newline. None of those may survive into the Content-Disposition header: a
    raw newline is a response-splitting vector, and an unescaped quote could
    break out of the quoted filename="..." value."""
    hostile = 'Week 1/2 "Notes"\nInjected-Header: evil'
    monkeypatch.setattr(relay.drive_client, "get_metadata", lambda fid: owned_folder(hostile))
    monkeypatch.setattr(relay.tree.drive_client, "get_metadata", lambda fid: owned_folder(hostile))
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 5)]
    drive["bodies"] = {"a": b"INTRO"}

    disposition = client.get("/api/drive/zip", params={"url": FOLDER_URL}).headers[
        "content-disposition"
    ]

    # The defining property: no control character survives into the header,
    # so nothing can be mistaken for a second header line by any client.
    assert "\n" not in disposition
    assert "\r" not in disposition
    # The slash must not survive as a literal path separator in the plain
    # filename half of the header.
    ascii_half = disposition.split(";")[1]
    assert "/" not in ascii_half
    # A single well-formed header line: exactly the two expected parameters.
    assert disposition.startswith('attachment; filename="')
    assert "; filename*=UTF-8''" in disposition


def test_never_redirects_the_browser_to_google(drive):
    """The whole feature exists because participants cannot reach Google."""
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 5)]
    drive["bodies"] = {"a": b"INTRO"}

    response = client.get("/api/drive/zip", params={"url": FOLDER_URL}, follow_redirects=False)

    assert response.status_code == 200
    assert "location" not in {k.lower() for k in response.headers}


def test_zip_rejects_a_bad_link():
    response = client.get("/api/drive/zip", params={"url": "https://example.com/x"})

    assert response.status_code == 400
    assert response.json()["detail"] == relay.BAD_LINK


def test_zip_refuses_a_folder_over_the_cap(drive):
    drive["children"][FOLDER_ID] = [pdf("a", "Huge.bin", relay.MAX_TRANSFER_BYTES + 1)]

    response = client.get("/api/drive/zip", params={"url": FOLDER_URL})

    assert response.status_code == 413
    assert response.json()["detail"] == relay.TOO_LARGE


def test_a_single_file_link_streams_that_file_not_a_zip(drive, monkeypatch):
    single = pdf("f1", "Deck.pdf", 4)
    monkeypatch.setattr(relay.drive_client, "get_metadata", lambda fid: DriveFile(
        id="f1", name="Deck.pdf", mime_type="application/pdf", size=4,
        owners=(DriveOwner(email="victorrentea@gmail.com", permission_id="1", display_name="V"),),
        shortcut_target_id=None))
    monkeypatch.setattr(relay.drive_client, "open_download", lambda file: iter([b"PDF!"]))

    response = client.get(
        "/api/drive/zip",
        params={"url": f"https://drive.google.com/file/d/{FOLDER_ID}/view"},
    )

    assert response.status_code == 200
    assert response.content == b"PDF!"
    assert response.headers["content-type"] == "application/pdf"
    assert "Deck.pdf" in response.headers["content-disposition"]
    assert single.name == "Deck.pdf"


def test_rate_limiter_allows_three_downloads_then_throttles(monkeypatch, drive):
    monkeypatch.delenv("GATEWAY_RATE_LIMIT_DISABLED", raising=False)
    monkeypatch.setattr(rate_limit, "_EXEMPT_PEERS", frozenset())
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 5)]
    drive["bodies"] = {"a": b"INTRO"}
    headers = {"X-Forwarded-For": "203.0.113.7"}

    codes = [
        client.get("/api/drive/zip", params={"url": FOLDER_URL}, headers=headers).status_code
        for _ in range(4)
    ]

    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429


def test_preview_is_not_throttled_by_the_zip_bucket(monkeypatch, drive):
    monkeypatch.delenv("GATEWAY_RATE_LIMIT_DISABLED", raising=False)
    monkeypatch.setattr(rate_limit, "_EXEMPT_PEERS", frozenset())
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 5)]
    drive["bodies"] = {"a": b"INTRO"}
    headers = {"X-Forwarded-For": "203.0.113.8"}

    for _ in range(4):
        client.get("/api/drive/zip", params={"url": FOLDER_URL}, headers=headers)

    assert client.get("/api/drive/preview", params={"url": FOLDER_URL},
                      headers=headers).status_code == 200
