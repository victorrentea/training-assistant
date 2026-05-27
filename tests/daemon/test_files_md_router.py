"""Tests for GET /api/participant/files-md endpoint."""
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon import files_md
from daemon.misc.router import participant_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture
def session_folder(tmp_path: Path, monkeypatch):
    folder = tmp_path / "session"
    folder.mkdir()
    monkeypatch.setattr(
        "daemon.misc.content_files.get_active_session_folder", lambda: folder
    )
    yield folder


def test_files_md_endpoint_no_active_session(monkeypatch):
    monkeypatch.setattr(
        "daemon.misc.content_files.get_active_session_folder", lambda: None
    )
    client = _client()
    resp = client.get("/api/participant/files-md")
    assert resp.status_code == 200
    body = resp.json()
    assert body["raw_markdown"] == files_md.EMPTY_STATE
    assert body["updated_at"] is None


def test_files_md_endpoint_empty_session(session_folder):
    client = _client()
    resp = client.get("/api/participant/files-md")
    assert resp.status_code == 200
    body = resp.json()
    assert body["raw_markdown"] == files_md.EMPTY_STATE
    assert body["updated_at"] is None


def test_files_md_endpoint_returns_sanitized_markdown(session_folder):
    (session_folder / "files.md").write_text(
        "# Files opened this session\n\n"
        "## [repo](https://github.com/owner/repo) <!-- default_branch:main -->\n\n"
        "- [a.py](https://github.com/owner/repo/blob/main/src/a.py)"
        " <!-- ts:2026-05-27T10:00:00Z path:src/a.py -->\n",
        encoding="utf-8",
    )
    client = _client()
    resp = client.get("/api/participant/files-md")
    assert resp.status_code == 200
    body = resp.json()
    assert "<!--" not in body["raw_markdown"]
    assert "## [repo](https://github.com/owner/repo)" in body["raw_markdown"]
    assert "- [a.py](https://github.com/owner/repo/blob/main/src/a.py)" in body["raw_markdown"]
    assert body["updated_at"] is not None  # ISO timestamp from file mtime
