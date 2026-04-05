"""Unit tests for daemon slides /check endpoint (daemon/slides/router.py)."""
import asyncio
import threading
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import daemon.slides.router as slides_router
from daemon.slides.router import participant_router, handle_pdf_download_complete
from daemon.misc.state import MiscState


@pytest.fixture(autouse=True)
def reset_module_state():
    """Reset module-level state between tests."""
    old_pending = slides_router._pending_checks
    old_loop = slides_router._event_loop
    old_timeout = slides_router._CHECK_TIMEOUT_S
    slides_router._pending_checks = {}
    slides_router._event_loop = None
    yield
    slides_router._pending_checks = old_pending
    slides_router._event_loop = old_loop
    slides_router._CHECK_TIMEOUT_S = old_timeout


@pytest.fixture
def fresh_misc_state():
    """Provide a clean MiscState for each test."""
    ms = MiscState()
    with patch("daemon.slides.router.misc_state", ms):
        yield ms


@pytest.fixture
def client(fresh_misc_state):
    """TestClient with participant slides router mounted."""
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app, raise_server_exceptions=False)


def test_check_returns_200_when_cached(client, fresh_misc_state):
    """When cache status is already 'cached', /check returns 200 immediately."""
    fresh_misc_state.slides_cache_status["myslug"] = {"status": "cached"}

    resp = client.get("/test-session/api/slides/check/myslug")

    assert resp.status_code == 200
    assert resp.json()["status"] == "cached"


def test_check_triggers_download_and_returns_200_on_success(fresh_misc_state, monkeypatch):
    """Not cached: triggers download, resolves future with 'ok' → 200."""
    # Mock send_to_railway to do nothing but record the call
    sent_msgs = []

    def fake_send_to_railway(msg):
        sent_msgs.append(msg)
        return True

    monkeypatch.setattr("daemon.ws_publish.send_to_railway", fake_send_to_railway)

    # Also mock broadcast and SlidesCacheStatusMsg since handle_pdf_download_complete uses them
    with patch("daemon.ws_publish.broadcast"), \
         patch("daemon.ws_messages.SlidesCacheStatusMsg"):

        app = FastAPI()
        app.include_router(participant_router)
        client = TestClient(app, raise_server_exceptions=False)

        def resolve_after_delay():
            # Small delay to let the endpoint register the future
            import time
            time.sleep(0.05)
            handle_pdf_download_complete({"slug": "myslug", "status": "ok"})

        t = threading.Thread(target=resolve_after_delay, daemon=True)
        t.start()

        resp = client.get("/test-session/api/slides/check/myslug")
        t.join(timeout=5.0)

    assert resp.status_code == 200
    assert resp.json()["status"] == "cached"
    # Verify download_pdf was sent to Railway
    assert any(m.get("type") == "download_pdf" and m.get("slug") == "myslug" for m in sent_msgs)


def test_check_returns_503_on_timeout(fresh_misc_state, monkeypatch):
    """No cached entry + no download completion → 503 after timeout."""
    monkeypatch.setattr(slides_router, "_CHECK_TIMEOUT_S", 0.1)

    def fake_send_to_railway(msg):
        return True

    monkeypatch.setattr("daemon.ws_publish.send_to_railway", fake_send_to_railway)

    app = FastAPI()
    app.include_router(participant_router)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/test-session/api/slides/check/myslug")

    assert resp.status_code == 503
    assert resp.json()["status"] == "timeout"


def test_check_coalesces_concurrent_requests(fresh_misc_state, monkeypatch):
    """Two concurrent /check requests for the same slug send only one download_pdf message.

    We verify the coalescing behavior directly: the second request that arrives while the
    first is pending skips sending another download_pdf message.
    """
    import asyncio as _asyncio

    sent_msgs = []

    def fake_send_to_railway(msg):
        sent_msgs.append(msg)
        return True

    monkeypatch.setattr("daemon.ws_publish.send_to_railway", fake_send_to_railway)

    async def _run():
        # Build a minimal ASGI app with the router
        from fastapi import FastAPI as _FastAPI
        _app = _FastAPI()
        _app.include_router(participant_router)

        import httpx
        from httpx import AsyncClient
        transport = httpx.ASGITransport(app=_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            with patch("daemon.ws_publish.broadcast"), \
                 patch("daemon.ws_messages.SlidesCacheStatusMsg"):
                # Fire two concurrent requests before resolving
                t1 = _asyncio.create_task(
                    ac.get("/test-session/api/slides/check/myslug")
                )
                t2 = _asyncio.create_task(
                    ac.get("/test-session/api/slides/check/myslug")
                )

                # Let both tasks get to the await point
                await _asyncio.sleep(0.05)

                # Resolve: both futures should be resolved via the event loop
                handle_pdf_download_complete({"slug": "myslug", "status": "ok"})

                r1, r2 = await _asyncio.gather(t1, t2)

        return r1, r2

    r1, r2 = asyncio.run(_run())

    # Both requests should return 200
    assert r1.status_code == 200, f"Request 1 returned {r1.status_code}"
    assert r2.status_code == 200, f"Request 2 returned {r2.status_code}"

    # Only one download_pdf message should have been sent (coalescing)
    download_msgs = [m for m in sent_msgs if m.get("type") == "download_pdf"]
    assert len(download_msgs) == 1, f"Expected 1 download_pdf, got {len(download_msgs)}: {download_msgs}"
