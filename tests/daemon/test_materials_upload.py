import types

from daemon.materials.upload import build_multipart, handle_build_materials_zip


def _config(tmp_path):
    return types.SimpleNamespace(
        session_folder=tmp_path,
        server_url="https://interact.example.test",
        host_username="host",
        host_password="secret",
    )


def test_build_multipart_encodes_fields_and_file():
    body, boundary = build_multipart(
        {"session_id": "e2etst", "filename": "Session.zip"}, ("Session.zip", b"PK\x03\x04")
    )
    assert f"--{boundary}".encode() in body
    assert b'name="session_id"' in body
    assert b"e2etst" in body
    assert b'name="file"; filename="Session.zip"' in body
    assert b"PK\x03\x04" in body
    assert body.endswith(f"--{boundary}--\r\n".encode())


def test_build_multipart_without_file_part():
    body, boundary = build_multipart({"session_id": "e2etst", "error": "boom"}, None)
    assert b'name="error"' in body
    assert b"boom" in body
    assert b'name="file"' not in body


def test_handler_posts_archive(tmp_path, monkeypatch):
    (tmp_path / "ai-summary.md").write_text("summary", encoding="utf-8")
    posted = {}

    def _fake_post(url, body, boundary, config):
        posted["url"] = url
        posted["body"] = body

    monkeypatch.setattr("daemon.materials.upload._post_multipart", _fake_post)
    handle_build_materials_zip({"session_id": "e2etst"}, _config(tmp_path))

    assert posted["url"] == "https://interact.example.test/api/materials/zip/upload"
    assert b'name="file"' in posted["body"]
    assert b'name="error"' not in posted["body"]


def test_handler_reports_error_when_folder_missing(tmp_path, monkeypatch):
    posted = {}

    def _fake_post(url, body, boundary, config):
        posted["body"] = body

    monkeypatch.setattr("daemon.materials.upload._post_multipart", _fake_post)
    config = _config(tmp_path / "missing")
    handle_build_materials_zip({"session_id": "e2etst"}, config)

    assert b'name="error"' in posted["body"]
    assert b'name="file"' not in posted["body"]


def test_handler_reports_error_when_zip_too_large(tmp_path, monkeypatch):
    import daemon.materials.zip_builder as builder

    monkeypatch.setattr(builder, "MAX_ZIP_BYTES", 16)
    (tmp_path / "payload.bin").write_bytes(bytes(range(256)) * 64)
    posted = {}

    def _fake_post(url, body, boundary, config):
        posted["body"] = body

    monkeypatch.setattr("daemon.materials.upload._post_multipart", _fake_post)
    handle_build_materials_zip({"session_id": "e2etst"}, _config(tmp_path))

    assert b'name="error"' in posted["body"]
    assert b"limit" in posted["body"]


def test_handler_survives_no_session_folder_configured(monkeypatch):
    posted = {}

    def _fake_post(url, body, boundary, config):
        posted["body"] = body

    monkeypatch.setattr("daemon.materials.upload._post_multipart", _fake_post)
    config = types.SimpleNamespace(
        session_folder=None,
        server_url="https://interact.example.test",
        host_username="host",
        host_password="secret",
    )
    handle_build_materials_zip({"session_id": "e2etst"}, config)

    assert b'name="error"' in posted["body"]
