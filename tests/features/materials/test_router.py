import asyncio
import base64
import os

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
    # The daemon never answers here, so the final GET waits out the build
    # timeout before falling back to the stale archive. Keep that short —
    # the real 20s would be paid on every CI push.
    monkeypatch.setattr(materials, "BUILD_TIMEOUT_S", 0.2)
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
