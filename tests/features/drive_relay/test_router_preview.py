import pytest
from fastapi.testclient import TestClient

from railway.app import app
from railway.features.drive_relay import router as relay
from railway.features.drive_relay.drive_client import FOLDER_MIME, DriveError, DriveFile, DriveOwner

FOLDER_ID = "1A2b3C4d5E6f7G8h9I0jKlMnOpQrStUv"
FOLDER_URL = f"https://drive.google.com/drive/folders/{FOLDER_ID}"

client = TestClient(app)


def owned_folder():
    return DriveFile(
        id=FOLDER_ID, name="Workshop Materials", mime_type=FOLDER_MIME, size=None,
        owners=(DriveOwner(email="victorrentea@gmail.com", permission_id="1", display_name="V"),),
        shortcut_target_id=None,
    )


def pdf(id, name, size):
    return DriveFile(id=id, name=name, mime_type="application/pdf", size=size, owners=(),
                     shortcut_target_id=None)


@pytest.fixture(autouse=True)
def owner_env(monkeypatch):
    monkeypatch.setenv("DRIVE_OWNER_EMAILS", "victorrentea@gmail.com")
    monkeypatch.setenv("GOOGLE_DRIVE_API_KEY", "test-key")
    monkeypatch.setenv("GATEWAY_RATE_LIMIT_DISABLED", "1")


@pytest.fixture
def drive(monkeypatch):
    state = {"root": owned_folder(), "children": {}}
    monkeypatch.setattr(relay.drive_client, "get_metadata", lambda fid: state["root"])
    monkeypatch.setattr(relay.tree.drive_client, "get_metadata", lambda fid: state["root"])
    monkeypatch.setattr(relay.tree.drive_client, "list_children",
                        lambda fid: state["children"].get(fid, []))
    return state


def test_preview_reports_the_folder_contents(drive):
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 1000), pdf("b", "Lab.pdf", 2000)]

    response = client.get("/api/drive/preview", params={"url": FOLDER_URL})

    assert response.status_code == 200
    assert response.json() == {
        "name": "Workshop Materials",
        "file_count": 2,
        "total_bytes": 3000,
        "has_unsized_files": False,
    }


def test_preview_flags_unsized_native_files(drive):
    drive["children"][FOLDER_ID] = [
        DriveFile(id="d", name="Agenda", mime_type="application/vnd.google-apps.document",
                  size=None, owners=(), shortcut_target_id=None)
    ]

    body = client.get("/api/drive/preview", params={"url": FOLDER_URL}).json()

    assert body["has_unsized_files"] is True
    assert body["total_bytes"] == 0


def test_preview_rejects_a_non_drive_link():
    response = client.get("/api/drive/preview", params={"url": "https://example.com/x"})

    assert response.status_code == 400
    assert response.json()["detail"] == relay.BAD_LINK


def test_preview_rejects_a_folder_owned_by_someone_else(drive, monkeypatch):
    stranger = DriveFile(id=FOLDER_ID, name="Someone Else", mime_type=FOLDER_MIME, size=None,
                         owners=(DriveOwner(email="x@y.com", permission_id="9", display_name=""),),
                         shortcut_target_id=None)
    monkeypatch.setattr(relay.drive_client, "get_metadata", lambda fid: stranger)

    response = client.get("/api/drive/preview", params={"url": FOLDER_URL})

    assert response.status_code == 403
    assert response.json()["detail"] == relay.NOT_AVAILABLE


def test_403_and_404_are_indistinguishable_to_the_caller(drive, monkeypatch):
    """The message must not reveal which folders belong to the trainer."""
    def missing(fid):
        raise DriveError(404, "gone")

    monkeypatch.setattr(relay.drive_client, "get_metadata", missing)
    not_found = client.get("/api/drive/preview", params={"url": FOLDER_URL})

    assert not_found.status_code == 404
    assert not_found.json()["detail"] == relay.NOT_AVAILABLE


def test_preview_maps_drive_outage_to_502(drive, monkeypatch):
    def unreachable(fid):
        raise DriveError(502, "boom")

    monkeypatch.setattr(relay.drive_client, "get_metadata", unreachable)

    response = client.get("/api/drive/preview", params={"url": FOLDER_URL})

    assert response.status_code == 502
    assert response.json()["detail"] == relay.DRIVE_DOWN


def test_preview_refuses_a_folder_over_the_cap(drive):
    drive["children"][FOLDER_ID] = [pdf("a", "Huge.bin", relay.MAX_TRANSFER_BYTES + 1)]

    response = client.get("/api/drive/preview", params={"url": FOLDER_URL})

    assert response.status_code == 413
    assert response.json()["detail"] == relay.TOO_LARGE


def test_preview_works_with_no_active_session(drive):
    """The whole point: no session, no daemon, still answers."""
    from railway.shared.state import state
    state.reset()
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 10)]

    assert client.get("/api/drive/preview", params={"url": FOLDER_URL}).status_code == 200


def test_drive_routes_are_not_shadowed_by_the_session_catch_all():
    """Regression guard: /{session_id} must not swallow /api/drive/*."""
    routes = [r.path for r in app.routes]
    assert "/api/drive/preview" in routes
    assert routes.index("/api/drive/preview") < routes.index("/{session_id}/{tab}")
