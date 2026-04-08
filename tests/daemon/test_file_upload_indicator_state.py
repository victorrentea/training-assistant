from unittest.mock import patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.host_state_router import _build_host_participants_list
from daemon.misc.router import host_router
from daemon.misc.state import misc_state
from daemon.participant.state import participant_state
from daemon.upload import _do_download


def _reset_runtime_state() -> None:
    participant_state.reset()
    misc_state.reset_for_new_session()


def test_upload_download_persists_indicator_and_notifies_host(tmp_path):
    _reset_runtime_state()
    sent = []
    ack_calls = []

    class _Resp:
        def __init__(self, payload: bytes):
            self._payload = payload
            self._sent = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _size: int):
            if self._sent:
                return b""
            self._sent = True
            return self._payload

    with patch("daemon.upload.urllib.request.urlopen", return_value=_Resp(b"abc")), \
         patch("daemon.upload._post_json", side_effect=lambda *args, **kwargs: ack_calls.append((args, kwargs))), \
         patch("daemon.upload.send_to_railway", side_effect=lambda msg: sent.append(msg) or True):
        _do_download(
            "http://server",
            "host",
            "pwd",
            "sid123",
            42,
            "uuid-1",
            "report.pdf",
            3,
            tmp_path,
        )

    saved_file = tmp_path / "uploads" / "report.pdf"
    assert saved_file.exists()
    assert saved_file.read_bytes() == b"abc"
    visible = misc_state.visible_uploaded_files("uuid-1")
    assert len(visible) == 1
    assert visible[0]["id"] == "42"
    assert visible[0]["filename"] == "report.pdf"
    assert visible[0]["disk_path"] == str(saved_file.resolve())
    assert sent and sent[0]["type"] == "send_to_host"
    assert sent[0]["event"]["type"] == "file_uploaded"
    assert sent[0]["event"]["id"] == "42"
    assert ack_calls, "Daemon should ack upload back to Railway"
    _reset_runtime_state()


def test_host_participant_list_keeps_uploaded_files_and_seen_flag():
    _reset_runtime_state()
    participant_state.participant_names["uuid-1"] = "Alice"
    participant_state.scores["uuid-1"] = 50
    misc_state.uploaded_files["uuid-1"] = [
        {"id": "f1", "filename": "one.txt", "size": 10, "disk_path": "/tmp/one.txt", "seen_by_host": False},
        {"id": "f2", "filename": "two.txt", "size": 20, "disk_path": "/tmp/two.txt", "seen_by_host": True},
    ]

    participants = _build_host_participants_list()
    assert len(participants) == 1
    assert participants[0]["uuid"] == "uuid-1"
    assert len(participants[0]["received_files"]) == 2
    assert participants[0]["received_files"][0]["id"] == "f1"
    assert participants[0]["received_files"][1]["seen_by_host"] is True
    _reset_runtime_state()


def test_mark_uploaded_file_seen_endpoint_marks_state():
    _reset_runtime_state()
    app = FastAPI()
    app.include_router(host_router)
    client = TestClient(app)

    misc_state.add_uploaded_file("uuid-1", "f1", "a.txt", 1, "/tmp/a.txt")
    resp = client.post(
        "/api/session-1/host/uploads/seen",
        json={"uuid": "uuid-1", "file_id": "f1"},
    )
    assert resp.status_code == 204
    assert resp.content == b""
    visible = misc_state.visible_uploaded_files("uuid-1")
    assert len(visible) == 1
    assert visible[0]["seen_by_host"] is True
    _reset_runtime_state()
