# Session Materials Zip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let participants download the whole session folder as a zip through the Railway relay, so people behind firewalls that block `drive.google.com` can still get the materials.

**Architecture:** A participant hits `GET /{sid}/api/materials/zip` on Railway. If Railway has a zip younger than 60s it serves it. Otherwise it pushes a `build_materials_zip` WS message to the daemon and awaits a Future; the daemon zips the session folder from local disk (DriveFS mirror) and POSTs the archive back over multipart HTTP with host Basic auth, which resolves the Future. Concurrent requests share one build. Google is never in the path.

**Tech Stack:** FastAPI + Pydantic (Railway), stdlib `zipfile` + `urllib` (daemon, no `requests` outside dev extras), vanilla JS + Material Symbols (participant UI), pytest.

**Spec:** `docs/superpowers/specs/2026-07-28-session-materials-zip-design.md`

## Global Constraints

- All code, comments, and commit messages in English.
- `MAX_ZIP_BYTES = 25 * 1024 * 1024` — identical value on both daemon and Railway sides.
- `CACHE_TTL_S = 60.0`, `BUILD_TIMEOUT_S = 20.0`.
- Exclusion set, exactly: names `session-state.json`, `attendees.md`, `Icon`, `Icon\r`; globs `~$*`, `*.zip`; directories `.obsidian`.
- Pydantic models for API contracts — no raw dict payloads.
- Never edit `API.md` by hand; regenerate with `python3 scripts/generate_apis_md.py --output API.md`.
- Daemon logging via `daemon/log.py`; Railway→daemon direction uses `↑`/`↓` arrows per the project convention.
- This is **not** the `MaterialsMirrorRunner` removed in `dc1228ea`. No background tick, no per-file endpoints, no mirroring of `materials/`. Say so in module docstrings.
- Push to `master` after each task.

---

### Task 1: Daemon zip builder

Pure function, no I/O beyond reading the session folder. Hermetic and fast.

**Files:**
- Create: `daemon/materials/__init__.py` (empty)
- Create: `daemon/materials/zip_builder.py`
- Test: `tests/daemon/test_materials_zip_builder.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `build_session_zip(session_folder: Path) -> bytes`, `session_zip_filename(session_folder: Path) -> str`, `ZipTooLargeError`, `MAX_ZIP_BYTES: int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/daemon/test_materials_zip_builder.py
import io
import zipfile

import pytest

from daemon.materials.zip_builder import (
    MAX_ZIP_BYTES,
    ZipTooLargeError,
    build_session_zip,
    session_zip_filename,
)


def _entries(data: bytes) -> set[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return set(archive.namelist())


def _make_session(tmp_path):
    folder = tmp_path / "2026-07-27..29 Spring+Quarkus@DB"
    (folder / "wiki").mkdir(parents=True)
    (folder / ".obsidian").mkdir()
    (folder / "wiki" / "Dependency Injection.md").write_text("di", encoding="utf-8")
    (folder / "ai-summary.md").write_text("summary", encoding="utf-8")
    (folder / "Agenda.docx").write_bytes(b"docx")
    (folder / "files.md").write_text("files", encoding="utf-8")
    (folder / "session-state.json").write_text("{}", encoding="utf-8")
    (folder / "attendees.md").write_text("names", encoding="utf-8")
    (folder / "Icon").write_bytes(b"")
    (folder / "~$Agenda.docx").write_bytes(b"lock")
    (folder / "wiki.zip").write_bytes(b"PK")
    (folder / ".obsidian" / "workspace.json").write_text("{}", encoding="utf-8")
    return folder


def test_includes_content_with_relative_arcnames(tmp_path):
    folder = _make_session(tmp_path)
    entries = _entries(build_session_zip(folder))
    assert entries == {
        "wiki/Dependency Injection.md",
        "ai-summary.md",
        "Agenda.docx",
        "files.md",
    }


def test_excludes_internal_state_and_attendees(tmp_path):
    folder = _make_session(tmp_path)
    entries = _entries(build_session_zip(folder))
    assert "session-state.json" not in entries
    assert "attendees.md" not in entries


def test_excludes_junk_globs_and_obsidian_dir(tmp_path):
    folder = _make_session(tmp_path)
    entries = _entries(build_session_zip(folder))
    assert "Icon" not in entries
    assert "~$Agenda.docx" not in entries
    assert "wiki.zip" not in entries
    assert not any(entry.startswith(".obsidian/") for entry in entries)


def test_archive_content_round_trips(tmp_path):
    folder = _make_session(tmp_path)
    with zipfile.ZipFile(io.BytesIO(build_session_zip(folder))) as archive:
        assert archive.read("wiki/Dependency Injection.md") == b"di"


def test_missing_folder_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_session_zip(tmp_path / "does-not-exist")


def test_size_guard_trips(tmp_path, monkeypatch):
    import daemon.materials.zip_builder as builder

    monkeypatch.setattr(builder, "MAX_ZIP_BYTES", 128)
    folder = tmp_path / "big"
    folder.mkdir()
    # Random-ish bytes so DEFLATE cannot squeeze it under the cap.
    (folder / "payload.bin").write_bytes(bytes(range(256)) * 64)
    with pytest.raises(ZipTooLargeError):
        builder.build_session_zip(folder)


def test_filename_is_folder_name(tmp_path):
    folder = _make_session(tmp_path)
    assert session_zip_filename(folder) == "2026-07-27..29 Spring+Quarkus@DB.zip"


def test_max_zip_bytes_is_25mb():
    assert MAX_ZIP_BYTES == 25 * 1024 * 1024
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/test_materials_zip_builder.py -v --confcutdir=tests/daemon`
Expected: FAIL — `ModuleNotFoundError: No module named 'daemon.materials.zip_builder'`

- [ ] **Step 3: Write the implementation**

```python
# daemon/materials/zip_builder.py
"""Build a downloadable zip of the current session folder.

This is NOT the MaterialsMirrorRunner removed in dc1228ea: nothing is synced
in the background, there are no per-file endpoints, and `materials/` is never
touched. One on-demand archive of the session folder, built when a
participant asks for it.
"""
from __future__ import annotations

import fnmatch
import io
import zipfile
from pathlib import Path

MAX_ZIP_BYTES = 25 * 1024 * 1024

# "Icon\r" is the real name of the macOS custom-folder-icon file; Finder and
# `ls` both render it as "Icon".
EXCLUDED_NAMES = frozenset({"session-state.json", "attendees.md", "Icon", "Icon\r"})
EXCLUDED_GLOBS = ("~$*", "*.zip")
EXCLUDED_DIRS = frozenset({".obsidian"})


class ZipTooLargeError(RuntimeError):
    """The built archive exceeds MAX_ZIP_BYTES."""


def _is_excluded_name(name: str) -> bool:
    if name in EXCLUDED_NAMES:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in EXCLUDED_GLOBS)


def build_session_zip(session_folder: Path) -> bytes:
    """Return a DEFLATE archive of session_folder, minus the exclusion set.

    Raises FileNotFoundError if the folder is missing, ZipTooLargeError if the
    result exceeds MAX_ZIP_BYTES.
    """
    if not session_folder.is_dir():
        raise FileNotFoundError(f"Session folder not found: {session_folder}")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(session_folder.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(session_folder)
            if any(part in EXCLUDED_DIRS for part in relative.parts[:-1]):
                continue
            if _is_excluded_name(path.name):
                continue
            archive.write(path, arcname=str(relative))

    data = buffer.getvalue()
    if len(data) > MAX_ZIP_BYTES:
        raise ZipTooLargeError(
            f"Session zip is {len(data) / 1024 / 1024:.1f} MB "
            f"(limit {MAX_ZIP_BYTES // 1024 // 1024} MB)"
        )
    return data


def session_zip_filename(session_folder: Path) -> str:
    """Participant-facing filename, e.g. '2026-07-27..29 Spring+Quarkus@DB.zip'."""
    return f"{session_folder.name}.zip"
```

Also create an empty `daemon/materials/__init__.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/test_materials_zip_builder.py -v --confcutdir=tests/daemon`
Expected: 8 passed

- [ ] **Step 5: Commit and push**

```bash
git add daemon/materials/__init__.py daemon/materials/zip_builder.py tests/daemon/test_materials_zip_builder.py
git commit -m "feat(materials): zip the session folder, minus internal state and junk"
git push origin master
```

---

### Task 2: Railway endpoints — serve, cache, dedup, receive

**Files:**
- Create: `railway/features/materials/__init__.py` (empty)
- Create: `railway/features/materials/router.py`
- Modify: `railway/features/ws/daemon_protocol.py` (add message constant after line 29)
- Modify: `railway/app.py` (mount both routers)
- Test: `tests/features/materials/__init__.py` (empty), `tests/features/materials/test_router.py`

**Interfaces:**
- Consumes: `MSG_BUILD_MATERIALS_ZIP` and `push_to_daemon` from `railway/features/ws/daemon_protocol.py`; `state` from `railway/shared/state.py`; `require_host_auth` from `railway/shared/auth.py`.
- Produces: `GET /{session_id}/api/materials/zip` (participant), `POST /api/materials/zip/upload` (daemon, host auth), `reset_materials_cache()` for tests, `MaterialsZipUploadResponse`.

**Note on the Future contract:** the pending build Future resolves to `str | None` — `None` means success, a non-empty string is the daemon's error message. It is never rejected with an exception, which avoids Python's "Future exception was never retrieved" warnings when a waiter has already timed out.

- [ ] **Step 1: Write the failing tests**

```python
# tests/features/materials/test_router.py
import asyncio
import base64
import os

import pytest
from fastapi.testclient import TestClient

from railway.app import app, state
from railway.features.materials import router as materials

_HOST_AUTH_HEADERS = {
    "Authorization": "Basic " + base64.b64encode(
        f"{os.environ.get('HOST_USERNAME', 'host')}:{os.environ.get('HOST_PASSWORD', 'host')}".encode()
    ).decode()
}

ZIP_BYTES = b"PK\x03\x04fake-archive-body"


def setup_function():
    state.reset()
    state.session_id = "e2etst"
    materials.reset_materials_cache()


def teardown_function():
    materials.reset_materials_cache()
    state.reset()


def _upload(client, **overrides):
    data = {"session_id": "e2etst", "filename": "Session.zip"}
    data.update(overrides.pop("data", {}))
    files = overrides.pop("files", {"file": ("Session.zip", ZIP_BYTES, "application/zip")})
    return client.post(
        "/api/materials/zip/upload", data=data, files=files, headers=_HOST_AUTH_HEADERS
    )


def test_upload_requires_host_auth():
    with TestClient(app) as client:
        response = client.post(
            "/api/materials/zip/upload",
            data={"session_id": "e2etst", "filename": "Session.zip"},
            files={"file": ("Session.zip", ZIP_BYTES, "application/zip")},
        )
    assert response.status_code == 401


def test_fresh_cache_is_served_without_touching_the_daemon(monkeypatch):
    pushed = []

    async def _fake_push(msg):
        pushed.append(msg)
        return True

    monkeypatch.setattr(materials, "push_to_daemon", _fake_push)
    with TestClient(app) as client:
        assert _upload(client).status_code == 200
        response = client.get("/e2etst/api/materials/zip")

    assert response.status_code == 200
    assert response.content == ZIP_BYTES
    assert response.headers["content-type"] == "application/zip"
    assert "Session.zip" in response.headers["content-disposition"]
    assert pushed == []  # cache was fresh — no build requested


def test_stale_cache_is_served_when_daemon_is_gone(monkeypatch):
    async def _fake_push(msg):
        return False  # daemon not connected

    monkeypatch.setattr(materials, "push_to_daemon", _fake_push)
    with TestClient(app) as client:
        assert _upload(client).status_code == 200
        materials.expire_cache_for_test()
        response = client.get("/e2etst/api/materials/zip")

    assert response.status_code == 200
    assert response.content == ZIP_BYTES


def test_no_cache_and_no_daemon_returns_503(monkeypatch):
    async def _fake_push(msg):
        return False

    monkeypatch.setattr(materials, "push_to_daemon", _fake_push)
    with TestClient(app) as client:
        response = client.get("/e2etst/api/materials/zip")
    assert response.status_code == 503


def test_daemon_reported_error_does_not_clobber_cache(monkeypatch):
    async def _fake_push(msg):
        return True

    monkeypatch.setattr(materials, "push_to_daemon", _fake_push)
    with TestClient(app) as client:
        assert _upload(client).status_code == 200
        error_response = client.post(
            "/api/materials/zip/upload",
            data={"session_id": "e2etst", "error": "Session zip is 41.0 MB (limit 25 MB)"},
            headers=_HOST_AUTH_HEADERS,
        )
        assert error_response.status_code == 200
        assert error_response.json()["ok"] is False
        materials.expire_cache_for_test()
        response = client.get("/e2etst/api/materials/zip")

    assert response.status_code == 200
    assert response.content == ZIP_BYTES  # previous archive survived


def test_upload_rejects_oversized_body(monkeypatch):
    monkeypatch.setattr(materials, "MAX_ZIP_BYTES", 16)
    with TestClient(app) as client:
        response = _upload(client, files={"file": ("Session.zip", b"x" * 64, "application/zip")})
    assert response.status_code == 413


def test_upload_without_file_or_error_is_422():
    with TestClient(app) as client:
        response = client.post(
            "/api/materials/zip/upload",
            data={"session_id": "e2etst"},
            headers=_HOST_AUTH_HEADERS,
        )
    assert response.status_code == 422


def test_concurrent_requests_trigger_one_build(monkeypatch):
    """Five simultaneous clicks must cost the trainer's laptop one zip build."""
    pushed = []

    async def _fake_push(msg):
        pushed.append(msg)
        return True

    monkeypatch.setattr(materials, "push_to_daemon", _fake_push)

    async def _scenario():
        materials.reset_materials_cache()
        waiters = [asyncio.create_task(materials.request_build()) for _ in range(5)]
        # Yield enough times for every task to get past the dedup check and
        # park on the shared Future; a single sleep(0) only schedules one.
        for _ in range(10):
            await asyncio.sleep(0)
        materials.resolve_pending_build(None)
        return await asyncio.gather(*waiters)

    results = asyncio.run(_scenario())

    assert len(pushed) == 1
    assert results == [None] * 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/features/materials/ -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'railway.features.materials'`

- [ ] **Step 3: Add the WS message constant**

In `railway/features/ws/daemon_protocol.py`, after the `MSG_FILE_READY_FOR_DOWNLOAD` block (line 29):

```python
# --- Session materials zip build request (backend → daemon) ---
MSG_BUILD_MATERIALS_ZIP = "build_materials_zip"
```

- [ ] **Step 4: Write the router**

```python
# railway/features/materials/router.py
"""On-demand session materials zip for participants who cannot reach Google Drive.

This is NOT the materials mirror removed in dc1228ea: no background sync, no
per-file upsert/delete endpoints, and `materials/` is never mirrored. The
daemon builds one archive of the session folder when a participant asks, and
Railway caches it briefly.
"""
import asyncio
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from railway.features.ws.daemon_protocol import MSG_BUILD_MATERIALS_ZIP, push_to_daemon
from railway.shared.auth import require_host_auth
from railway.shared.state import state

router = APIRouter()  # daemon-facing, host auth
public_router = APIRouter()  # participant-facing, mounted under /{session_id}

logger = logging.getLogger(__name__)

MAX_ZIP_BYTES = 25 * 1024 * 1024
CACHE_TTL_S = 60.0
BUILD_TIMEOUT_S = 20.0
MATERIALS_DIR = Path(".server-data") / "materials"
DEFAULT_ZIP_NAME = "session-materials.zip"

# Resolves to None on success or to the daemon's error message on failure.
# Never rejected — a rejected Future whose waiter already timed out produces
# "Future exception was never retrieved" noise in the logs.
_pending_build: asyncio.Future | None = None
_built_at: float = 0.0
_zip_filename: str = DEFAULT_ZIP_NAME


class MaterialsZipUploadResponse(BaseModel):
    ok: bool
    size: int = 0
    filename: str = ""


def reset_materials_cache() -> None:
    """Test helper: drop cached archive and in-flight build state."""
    global _pending_build, _built_at, _zip_filename
    _pending_build = None
    _built_at = 0.0
    _zip_filename = DEFAULT_ZIP_NAME
    if MATERIALS_DIR.exists():
        for stale in MATERIALS_DIR.glob("*.zip"):
            stale.unlink(missing_ok=True)


def expire_cache_for_test() -> None:
    """Test helper: keep the archive on disk but mark it stale."""
    global _built_at
    _built_at = 0.0


def resolve_pending_build(error: str | None) -> None:
    """Complete the in-flight build, if any."""
    global _pending_build
    if _pending_build is not None and not _pending_build.done():
        _pending_build.set_result(error)
    _pending_build = None


def _zip_path(session_id: str) -> Path:
    safe = (session_id or "nosession").strip() or "nosession"
    return MATERIALS_DIR / f"{safe}.zip"


def _cache_is_fresh() -> bool:
    return _built_at > 0.0 and (time.monotonic() - _built_at) < CACHE_TTL_S


async def request_build() -> str | None:
    """Ask the daemon to build and upload the zip. Returns an error message or None.

    Concurrent callers share one build — the same dedup shape as
    `_pending_refresh` in railway/features/slides/router.py.
    """
    global _pending_build
    if _pending_build is not None and not _pending_build.done():
        return await asyncio.wait_for(asyncio.shield(_pending_build), timeout=BUILD_TIMEOUT_S)

    loop = asyncio.get_running_loop()
    _pending_build = loop.create_future()
    pending = _pending_build
    sent = await push_to_daemon(
        {"type": MSG_BUILD_MATERIALS_ZIP, "session_id": state.session_id or ""}
    )
    if not sent:
        resolve_pending_build("Trainer not connected")
        return "Trainer not connected"
    return await asyncio.wait_for(asyncio.shield(pending), timeout=BUILD_TIMEOUT_S)


@public_router.get("/api/materials/zip", operation_id="get_materials_zip")
async def get_materials_zip():
    """Serve the session materials archive, rebuilding it when the cache is stale."""
    path = _zip_path(state.session_id or "")
    if not (path.exists() and _cache_is_fresh()):
        try:
            error = await request_build()
        except asyncio.TimeoutError:
            error = f"Build timed out after {BUILD_TIMEOUT_S:.0f}s"
        if error:
            # Stale is better than nothing: a participant clicking this button
            # usually has no working alternative.
            logger.warning("[materials] zip build failed: %s", error)

    if not path.exists():
        raise HTTPException(status_code=503, detail="Session materials are not available right now")

    return FileResponse(
        path=path,
        media_type="application/zip",
        filename=_zip_filename,
        headers={"Cache-Control": "no-cache"},
    )


@router.post(
    "/api/materials/zip/upload",
    response_model=MaterialsZipUploadResponse,
    dependencies=[Depends(require_host_auth)],
)
async def upload_materials_zip(
    session_id: str = Form(...),
    filename: str = Form(default=""),
    error: str = Form(default=""),
    file: UploadFile | None = File(default=None),
):
    """Receive the archive (or a build error) from the daemon."""
    global _built_at, _zip_filename

    if error:
        resolve_pending_build(error)
        return MaterialsZipUploadResponse(ok=False)

    if file is None:
        raise HTTPException(status_code=422, detail="file or error is required")

    MATERIALS_DIR.mkdir(parents=True, exist_ok=True)
    dest = _zip_path(session_id)
    tmp = dest.with_suffix(".zip.part")
    total = 0
    try:
        with open(tmp, "wb") as out:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ZIP_BYTES:
                    out.close()
                    tmp.unlink(missing_ok=True)
                    raise HTTPException(
                        413, f"Zip too large (max {MAX_ZIP_BYTES // (1024 * 1024)}MB)"
                    )
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise HTTPException(500, "Zip upload failed") from exc

    if total == 0:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "Empty zip")

    tmp.replace(dest)  # atomic swap so a concurrent GET never sees a partial file
    _zip_filename = filename or DEFAULT_ZIP_NAME
    _built_at = time.monotonic()
    resolve_pending_build(None)
    logger.info("[materials] ↓ received zip %s (%d bytes)", _zip_filename, total)
    return MaterialsZipUploadResponse(ok=True, size=total, filename=_zip_filename)
```

- [ ] **Step 5: Mount the routers in `railway/app.py`**

Add the import next to the other feature-router imports at the top:

```python
from railway.features.materials import router as materials
```

Register the daemon-facing router next to the other global daemon endpoints (immediately after the `slides.daemon_router` line, ~line 149):

```python
# Daemon-facing materials zip upload (global — daemon has no session_id prefix)
app.include_router(materials.router)
```

Register the participant-facing router on the live session router (immediately after the `slides.public_router` line, ~line 205):

```python
session_participant_live.include_router(materials.public_router)  # /api/materials/zip
```

Note: `materials.router` carries its own `Depends(require_host_auth)` on the endpoint, so it is included without a router-level dependency — unlike `slides.daemon_router`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/features/materials/ -v`
Expected: 8 passed

- [ ] **Step 7: Commit and push**

```bash
git add railway/features/materials railway/features/ws/daemon_protocol.py railway/app.py tests/features/materials
git commit -m "feat(materials): Railway endpoints to serve and receive the session zip"
git push origin master
```

---

### Task 3: Daemon WS handler — build on request, upload back

**Files:**
- Create: `daemon/materials/upload.py`
- Modify: `daemon/__main__.py` (register handler next to `file_ready_for_download`, ~line 808)
- Test: `tests/daemon/test_materials_upload.py`

**Interfaces:**
- Consumes: `build_session_zip`, `session_zip_filename`, `ZipTooLargeError` from Task 1; `MSG_BUILD_MATERIALS_ZIP` value `"build_materials_zip"` from Task 2.
- Produces: `handle_build_materials_zip(data: dict, config) -> None`, `build_multipart(fields: dict[str, str], file_part: tuple[str, bytes] | None) -> tuple[bytes, str]`.

The daemon has no `requests` dependency outside the dev extras, so multipart is hand-rolled over `urllib` — the same approach the removed `post_material_upsert_file` used.

- [ ] **Step 1: Write the failing tests**

```python
# tests/daemon/test_materials_upload.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/test_materials_upload.py -v --confcutdir=tests/daemon`
Expected: FAIL — `ModuleNotFoundError: No module named 'daemon.materials.upload'`

- [ ] **Step 3: Write the implementation**

```python
# daemon/materials/upload.py
"""Handle Railway's build_materials_zip request: zip the session folder and upload it.

Not a background mirror (see dc1228ea) — this only runs when Railway asks,
which only happens when a participant clicks the download button.
"""
from __future__ import annotations

import base64
import ssl
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from daemon import log
from daemon.materials.zip_builder import (
    ZipTooLargeError,
    build_session_zip,
    session_zip_filename,
)

_UPLOAD_PATH = "/api/materials/zip/upload"
_TIMEOUT_S = 30


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def build_multipart(
    fields: dict[str, str], file_part: tuple[str, bytes] | None
) -> tuple[bytes, str]:
    """Encode a multipart/form-data body. Returns (body, boundary)."""
    boundary = f"----materials-zip-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    if file_part is not None:
        filename, payload = file_part
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            (
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                "Content-Type: application/zip\r\n\r\n"
            ).encode()
        )
        chunks.append(payload)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def _post_multipart(url: str, body: bytes, boundary: str, config) -> None:
    token = base64.b64encode(
        f"{config.host_username}:{config.host_password}".encode()
    ).decode("ascii")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S, context=_ssl_context()):
        pass


def handle_build_materials_zip(data: dict, config) -> None:
    """Build the session zip and POST it to Railway; report failures the same way."""
    session_id = str(data.get("session_id") or "")
    folder: Path | None = getattr(config, "session_folder", None)
    url = f"{config.server_url}{_UPLOAD_PATH}"

    fields: dict[str, str] = {"session_id": session_id}
    file_part: tuple[str, bytes] | None = None

    try:
        if folder is None:
            raise FileNotFoundError("No active session folder")
        payload = build_session_zip(folder)
        filename = session_zip_filename(folder)
        fields["filename"] = filename
        file_part = (filename, payload)
        log.info("materials", f"↑ built session zip {filename} ({len(payload)} bytes)")
    except (FileNotFoundError, ZipTooLargeError, OSError) as exc:
        fields["error"] = str(exc)
        log.error("materials", f"Session zip build failed: {exc}")

    body, boundary = build_multipart(fields, file_part)
    try:
        _post_multipart(url, body, boundary, config)
    except (urllib.error.URLError, OSError) as exc:
        log.error("materials", f"Session zip upload failed: {exc}")
```

- [ ] **Step 4: Register the handler in `daemon/__main__.py`**

Add the import next to the existing `_handle_file_download` import (~line 54):

```python
from daemon.materials.upload import handle_build_materials_zip as _handle_materials_zip
```

Register it immediately after the existing `ws_client.register_handler("file_ready_for_download", ...)` block (~line 808):

```python
    ws_client.register_handler(
        "build_materials_zip",
        lambda data: _handle_materials_zip(data, config),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --extra dev --extra daemon pytest tests/daemon/test_materials_upload.py -v --confcutdir=tests/daemon`
Expected: 6 passed

- [ ] **Step 6: Commit and push**

```bash
git add daemon/materials/upload.py daemon/__main__.py tests/daemon/test_materials_upload.py
git commit -m "feat(materials): daemon builds and uploads the session zip on request"
git push origin master
```

---

### Task 4: Participant UI — download glyph next to Google Drive

**Files:**
- Modify: `static/participant.html` — nav row (line 793), initial-state wiring (line 3829), WS-update wiring (line 3915), `_applyGdriveToast` (line 3303)

**Interfaces:**
- Consumes: `GET /{sid}/api/materials/zip` from Task 2.
- Produces: nothing consumed by later tasks.

The Google Drive row is currently one anchor. A `<button>` cannot be nested inside `<a target="_blank">` (invalid HTML, and the click would navigate too), so the row becomes a flex wrapper with the anchor and the button as siblings.

- [ ] **Step 1: Restructure the nav row**

Replace the block at `static/participant.html:793-797`:

```html
<a id="gdrive-nav" href="#" target="_blank" rel="noopener" class="nav-item rounded-full px-2 py-2 flex items-center gap-3 transition-all cursor-pointer" style="display:none">
<span class="material-symbols-outlined flex-shrink-0">cloud</span>
<span class="text-base flex-1">Google Drive</span>
<span class="material-symbols-outlined flex-shrink-0" style="font-size:1rem;opacity:0.5">open_in_new</span>
</a>
```

with:

```html
<div id="gdrive-row" class="nav-item rounded-full px-2 py-2 flex items-center gap-3 transition-all" style="display:none">
<a id="gdrive-nav" href="#" target="_blank" rel="noopener" class="flex items-center gap-3 flex-1 cursor-pointer">
<span class="material-symbols-outlined flex-shrink-0">cloud</span>
<span class="text-base flex-1">Google Drive</span>
<span class="material-symbols-outlined flex-shrink-0" style="font-size:1rem;opacity:0.5">open_in_new</span>
</a>
<button id="gdrive-zip-btn" onclick="downloadMaterialsZip()" title="Download everything as .zip" class="flex-shrink-0 cursor-pointer" style="background:none;border:none;padding:0;color:inherit">
<span id="gdrive-zip-icon" class="material-symbols-outlined" style="font-size:1.1rem;opacity:0.6">download</span>
</button>
</div>
```

- [ ] **Step 2: Add the download handler**

Add next to `_applyGdriveToast` (after `static/participant.html:3309`). The helpers used here already exist in this file: `showToast(msg)` at line 2279, the `spin` keyframe at line 51, and the session-prefixed URL convention `'/' + _sessionId + '/api/...'` used by every other fetch in the file (e.g. line 1867).

```javascript
var _zipDownloading = false;

function downloadMaterialsZip() {
  if (_zipDownloading || !_sessionId) return;
  _zipDownloading = true;
  var icon = document.getElementById('gdrive-zip-icon');
  icon.textContent = 'progress_activity';
  icon.style.animation = 'spin 1s linear infinite';

  fetch('/' + _sessionId + '/api/materials/zip')
    .then(function (response) {
      if (!response.ok) throw new Error('HTTP ' + response.status);
      var disposition = response.headers.get('content-disposition') || '';
      var match = /filename="([^"]+)"/.exec(disposition);
      return response.blob().then(function (blob) {
        return { blob: blob, name: match ? match[1] : 'session-materials.zip' };
      });
    })
    .then(function (result) {
      var url = URL.createObjectURL(result.blob);
      var link = document.createElement('a');
      link.href = url;
      link.download = result.name;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    })
    .catch(function (err) {
      console.error('[participant] materials zip download failed:', err);
      showToast('Materials are not available right now — try again in a moment');
    })
    .finally(function () {
      _zipDownloading = false;
      icon.style.animation = '';
      icon.textContent = 'download';
    });
}
```

No new CSS or helper is needed — all three already exist in the file.

- [ ] **Step 3: Point the visibility wiring at the row**

At `static/participant.html:3829-3831`, replace:

```javascript
    var gdriveNav = document.getElementById('gdrive-nav');
    if (state.gdrive_url) { gdriveNav.href = state.gdrive_url; gdriveNav.style.display = ''; }
    else { gdriveNav.style.display = 'none'; }
```

with:

```javascript
    var gdriveNav = document.getElementById('gdrive-nav');
    var gdriveRow = document.getElementById('gdrive-row');
    if (state.gdrive_url) { gdriveNav.href = state.gdrive_url; gdriveRow.style.display = ''; }
    else { gdriveRow.style.display = 'none'; }
```

Apply the identical change to the WS-update path at `static/participant.html:3916-3918`, using `msg.gdrive_url` instead of `state.gdrive_url`.

- [ ] **Step 4: Add the zip link to the access-duration toast**

`_applyGdriveToast` (line 3303) currently shows only the Drive link. Add a sibling link that calls `downloadMaterialsZip()`. Inspect the toast markup first:

```bash
grep -n "access-duration-toast-gdrive" static/participant.html
```

Add an anchor next to `access-duration-toast-gdrive-link` in that markup:

```html
<a id="access-duration-toast-zip-link" href="#" onclick="downloadMaterialsZip(); return false;">download as .zip</a>
```

`_applyGdriveToast` already shows/hides the wrapper on `url`, so the new link needs no extra JS.

- [ ] **Step 5: Verify in the browser**

Start the daemon and open the participant page. Confirm:
- the Google Drive row renders with a `download` glyph on the right, vertically aligned
- clicking the row still opens Drive in a new tab
- clicking the glyph downloads a `.zip` whose entries match the expected set and contain no `session-state.json` / `attendees.md`
- clicking the glyph twice in a row does not fire two downloads

Take a screenshot of the sidebar row (proof for the task).

- [ ] **Step 6: Commit and push**

```bash
git add static/participant.html
git commit -m "feat(materials): download-zip glyph in the participant Google Drive row"
git push origin master
```

---

### Task 5: Hermetic E2E, docs, backlog

**Files:**
- Create: `tests/docker/test_materials_zip.py`
- Modify: `API.md` (regenerated, never hand-edited), `ARCHITECTURE.md`, `backlog.md`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: nothing.

- [ ] **Step 1: Write the hermetic round-trip test**

These tests use no pytest fixtures — there is no `tests/docker/conftest.py`. They use module-level constants plus `fresh_session()` from `session_utils`, exactly as `tests/docker/test_agenda_live.py` does. The daemon container sees the session folders under `SESSIONS_FOLDER`; find the active folder the same way `test_agenda_live.py` does, via `daemon_session_folder` from `/api/{session_id}/host/state`.

```python
# tests/docker/test_materials_zip.py
"""Hermetic E2E: participant downloads the session zip through the Railway relay.

Covers the full round trip — participant GET → Railway → WS build request →
daemon zips the local session folder → multipart upload → archive served —
and asserts the blacklist is applied.
"""

import base64
import io
import json
import os
import sys
import urllib.request
import zipfile

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
SESSIONS_FOLDER = os.environ.get("SESSIONS_FOLDER", "/tmp/test-sessions")
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")


def _active_session_folder(session_id: str) -> str:
    auth = base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()
    req = urllib.request.Request(
        f"{DAEMON_BASE}/api/{session_id}/host/state",
        headers={"Authorization": f"Basic {auth}"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())["daemon_session_folder"]


def test_participant_downloads_session_zip():
    session_id = fresh_session("MaterialsZip")
    folder = os.path.join(SESSIONS_FOLDER, _active_session_folder(session_id))

    with open(os.path.join(folder, "ai-summary.md"), "w", encoding="utf-8") as f:
        f.write("summary")
    with open(os.path.join(folder, "session-state.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    with open(os.path.join(folder, "attendees.md"), "w", encoding="utf-8") as f:
        f.write("names")
    os.makedirs(os.path.join(folder, "wiki"), exist_ok=True)
    with open(os.path.join(folder, "wiki", "Topic.md"), "w", encoding="utf-8") as f:
        f.write("topic")

    with urllib.request.urlopen(f"{BASE}/{session_id}/api/materials/zip", timeout=30) as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"] == "application/zip"
        payload = resp.read()

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        assert archive.read("wiki/Topic.md") == b"topic"

    assert "ai-summary.md" in names
    assert "wiki/Topic.md" in names
    assert "session-state.json" not in names
    assert "attendees.md" not in names
```

- [ ] **Step 2: Run the hermetic test**

Run: `bash tests/docker/run-hermetic.sh -k test_participant_downloads_session_zip -s`
Expected: PASS

- [ ] **Step 3: Regenerate `API.md`**

Run: `python3 scripts/generate_apis_md.py --output API.md`
Confirm the two new endpoints appear. Never edit `API.md` by hand.

- [ ] **Step 4: Update `ARCHITECTURE.md`**

Add the session-materials-zip flow to the daemon↔Railway interaction section: participant GET → Railway cache check → WS `build_materials_zip` → daemon zips the local session folder → multipart upload → Railway serves. State explicitly that Google Drive is not in the path, and that this is not the removed materials mirror.

- [ ] **Step 5: Add the backlog entry**

Prepend to `backlog.md`:

```markdown
- [x] feat(materials): participants can download the whole session folder as a zip via the Railway relay (`GET /{sid}/api/materials/zip`), for clients whose firewall blocks `drive.google.com`; daemon zips the local DriveFS folder on demand (excludes `session-state.json`, `attendees.md`, junk), Railway caches it 60s with in-flight dedup. Not a revival of the materials mirror removed in dc1228ea.
```

- [ ] **Step 6: Run the full check suite**

Run: `uv run --extra dev --extra daemon bash tests/check-all.sh`
Expected: all green. Capture the output as proof.

- [ ] **Step 7: Commit and push**

```bash
git add tests/docker/test_materials_zip.py API.md ARCHITECTURE.md backlog.md
git commit -m "test(materials): hermetic zip round-trip; regenerate API.md and docs"
git push origin master
```

- [ ] **Step 8: Verify in production**

This feature changes `railway/**`, so it triggers a real Railway redeploy — unlike most changes to this repo. After the deploy completes, confirm `/api/status` shows the new `git_sha`, then download the zip once from the live participant page and check the archive opens and excludes the blacklisted files.

---

## Notes for the implementer

- **Do not** add a background sync, a watcher, or a periodic upload. The archive is built only when a participant asks. A `MaterialsMirrorRunner` doing exactly that was removed in `dc1228ea`, deliberately.
- Traffic is a non-issue by design: the measured archive is ~130 KB versus ~7 MB for a single slide deck. Don't add gating, quotas, or "ask the trainer" flows.
- Daemon-only quick checks need `--confcutdir=tests/daemon` so the repo-root browser fixtures in `tests/conftest.py` don't leak in.
