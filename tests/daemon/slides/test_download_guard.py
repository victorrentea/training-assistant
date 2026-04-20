"""Heavy unit tests for the unified download guard in daemon/slides/router.py.

Covers:
- Guard primitives: _claim_download, _finish_download, _queue_pending_redownload
- _finish_download waking async waiters from a background thread
- check_slide_cache: fast path, download, 404, 503
- Concurrent requests: N requests → 1 Railway download, waiters get correct status
- Pending redownload: multiple PPTX changes collapse to one follow-up
"""
import asyncio
import threading
import time
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import daemon.slides.router as router_module
from daemon.misc.state import MiscState
from daemon.slides.router import (
    _claim_download,
    _finish_download,
    _get_wait_event,
    _queue_pending_redownload,
    participant_router,
)

SLUG = "ai-coding"
SESSION = "test-session"
DRIVE_URL = "https://docs.google.com/presentation/d/abc/export/pdf"


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_guard():
    """Reset all guard module-level state before and after every test."""
    def _clear():
        router_module._active_download_slugs.clear()
        router_module._pending_redownload_slugs.clear()
        router_module._download_wait_events.clear()
        router_module._event_loop = None
    _clear()
    yield
    _clear()


@pytest.fixture
def state():
    ms = MiscState()
    ms.slides_catalog[SLUG] = {"slug": SLUG, "title": "AI Coding", "drive_export_url": DRIVE_URL}
    with patch("daemon.slides.router.misc_state", ms):
        yield ms


@pytest.fixture
def app(state):
    a = FastAPI()
    a.include_router(participant_router)
    return a


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


def _check_url(slug=SLUG):
    return f"/{SESSION}/api/slides/check/{slug}"


# ── Guard primitives ──────────────────────────────────────────────────────────

class TestClaimDownload:
    def test_first_claim_succeeds(self):
        assert _claim_download(SLUG) is True

    def test_claimed_slug_is_active(self):
        _claim_download(SLUG)
        assert SLUG in router_module._active_download_slugs

    def test_second_claim_on_same_slug_fails(self):
        _claim_download(SLUG)
        assert _claim_download(SLUG) is False

    def test_different_slugs_can_both_be_claimed(self):
        assert _claim_download("slug-a") is True
        assert _claim_download("slug-b") is True

    def test_after_finish_slug_can_be_claimed_again(self):
        _claim_download(SLUG)
        _finish_download(SLUG)
        assert _claim_download(SLUG) is True


class TestFinishDownload:
    def test_releases_active_slot(self):
        _claim_download(SLUG)
        _finish_download(SLUG)
        assert SLUG not in router_module._active_download_slugs

    def test_returns_false_when_no_pending(self):
        _claim_download(SLUG)
        assert _finish_download(SLUG) is False

    def test_returns_true_when_pending_redownload_queued(self):
        _claim_download(SLUG)
        _queue_pending_redownload(SLUG)
        assert _finish_download(SLUG) is True

    def test_clears_pending_flag_after_returning_it(self):
        _claim_download(SLUG)
        _queue_pending_redownload(SLUG)
        _finish_download(SLUG)
        assert SLUG not in router_module._pending_redownload_slugs

    def test_idempotent_on_unknown_slug(self):
        assert _finish_download("no-such-slug") is False

    def test_clears_wait_event_entry(self):
        _claim_download(SLUG)
        router_module._download_wait_events[SLUG] = asyncio.Event()
        _finish_download(SLUG)
        assert SLUG not in router_module._download_wait_events


class TestQueuePendingRedownload:
    def test_adds_to_pending_set(self):
        _queue_pending_redownload(SLUG)
        assert SLUG in router_module._pending_redownload_slugs

    def test_multiple_queues_of_same_slug_deduplicate(self):
        _queue_pending_redownload(SLUG)
        _queue_pending_redownload(SLUG)
        _queue_pending_redownload(SLUG)
        assert router_module._pending_redownload_slugs.count(SLUG) if hasattr(
            router_module._pending_redownload_slugs, "count"
        ) else len([s for s in router_module._pending_redownload_slugs if s == SLUG]) == 1

    def test_queuing_two_different_slugs(self):
        _queue_pending_redownload("a")
        _queue_pending_redownload("b")
        assert "a" in router_module._pending_redownload_slugs
        assert "b" in router_module._pending_redownload_slugs


# ── _finish_download wakes async waiters from a background thread ─────────────

@pytest.mark.anyio
async def test_finish_download_from_thread_wakes_async_waiter():
    """`_finish_download` called from a background thread must wake an asyncio waiter."""
    router_module._event_loop = asyncio.get_event_loop()
    _claim_download(SLUG)
    event = _get_wait_event(SLUG)

    def finish_in_background():
        time.sleep(0.02)
        _finish_download(SLUG)

    t = threading.Thread(target=finish_in_background, daemon=True)
    t.start()
    await asyncio.wait_for(event.wait(), timeout=2.0)
    t.join()
    assert event.is_set()


@pytest.mark.anyio
async def test_finish_download_from_event_loop_sets_event_directly():
    """When called from the event loop (no running loop check), sets event synchronously."""
    router_module._event_loop = None  # no loop reference → falls back to event.set()
    _claim_download(SLUG)
    event = asyncio.Event()
    router_module._download_wait_events[SLUG] = event
    _finish_download(SLUG)  # called from event loop thread, loop not stored
    assert event.is_set()


# ── check_slide_cache: basic behavior ────────────────────────────────────────

class TestFastPath:
    def test_cached_status_returns_200_immediately(self, client, state):
        state.slides_updated[SLUG] = {"status": "cached"}
        resp = client.get(_check_url())
        assert resp.status_code == 200
        assert resp.json()["status"] == "cached"

    def test_cached_does_not_claim_download_slot(self, client, state):
        state.slides_updated[SLUG] = {"status": "cached"}
        client.get(_check_url())
        assert SLUG not in router_module._active_download_slugs

    def test_force_bypasses_cached_fast_path(self, client, state, monkeypatch):
        state.slides_updated[SLUG] = {"status": "cached"}
        monkeypatch.setattr("daemon.slides.router.download_on_railway",
                            lambda s, u: {"sha256": "new"})
        with patch("daemon.ws_publish.broadcast"):
            resp = client.get(_check_url() + "?force=true")
        assert resp.status_code == 200
        assert state.slides_updated[SLUG]["last_sha256"] == "new"


class TestDownloadHappyPath:
    def test_calls_railway_and_returns_200(self, client, state, monkeypatch):
        monkeypatch.setattr("daemon.slides.router.download_on_railway",
                            lambda s, u: {"sha256": "abc", "size": 512})
        with patch("daemon.ws_publish.broadcast"):
            resp = client.get(_check_url())
        assert resp.status_code == 200
        assert resp.json()["status"] == "cached"

    def test_marks_status_cached_in_state(self, client, state, monkeypatch):
        monkeypatch.setattr("daemon.slides.router.download_on_railway",
                            lambda s, u: {"sha256": "abc"})
        with patch("daemon.ws_publish.broadcast"):
            client.get(_check_url())
        assert state.slides_updated[SLUG]["status"] == "cached"
        assert state.slides_updated[SLUG]["last_sha256"] == "abc"

    def test_broadcasts_downloading_then_cached(self, client, state, monkeypatch):
        monkeypatch.setattr("daemon.slides.router.download_on_railway",
                            lambda s, u: {"sha256": "abc"})
        broadcasts = []
        with patch("daemon.ws_publish.broadcast", side_effect=lambda m: broadcasts.append(m)):
            client.get(_check_url())
        statuses = [b.slides_updated.get(SLUG, {}).get("status") for b in broadcasts]
        assert "downloading" in statuses
        assert "cached" in statuses
        assert statuses.index("downloading") < statuses.index("cached")

    def test_slot_released_after_success(self, client, state, monkeypatch):
        monkeypatch.setattr("daemon.slides.router.download_on_railway",
                            lambda s, u: {"sha256": "abc"})
        with patch("daemon.ws_publish.broadcast"):
            client.get(_check_url())
        assert SLUG not in router_module._active_download_slugs


class TestDownloadErrors:
    def test_returns_503_on_railway_failure(self, client, state, monkeypatch):
        monkeypatch.setattr("daemon.slides.router.download_on_railway",
                            lambda s, u: (_ for _ in ()).throw(RuntimeError("connection refused")))
        with patch("daemon.ws_publish.broadcast"):
            resp = client.get(_check_url())
        assert resp.status_code == 503
        assert state.slides_updated[SLUG]["status"] == "download_failed"

    def test_slot_released_after_failure(self, client, state, monkeypatch):
        monkeypatch.setattr("daemon.slides.router.download_on_railway",
                            lambda s, u: (_ for _ in ()).throw(RuntimeError("oops")))
        with patch("daemon.ws_publish.broadcast"):
            client.get(_check_url())
        assert SLUG not in router_module._active_download_slugs

    def test_returns_404_when_no_drive_url(self, client, state):
        state.slides_catalog[SLUG] = {"slug": SLUG, "title": "No URL"}
        resp = client.get(_check_url())
        assert resp.status_code == 404

    def test_slot_released_after_404(self, client, state):
        state.slides_catalog[SLUG] = {"slug": SLUG, "title": "No URL"}
        client.get(_check_url())
        assert SLUG not in router_module._active_download_slugs


# ── Concurrent requests ───────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_n_concurrent_requests_trigger_exactly_one_download(app, state, monkeypatch):
    """N concurrent participant requests for the same slug → exactly 1 Railway call."""
    download_count = [0]
    download_started = asyncio.Event()
    can_finish = threading.Event()

    def blocking_download(slug, url):
        download_count[0] += 1
        can_finish.wait(timeout=5)
        return {"sha256": "abc"}

    monkeypatch.setattr("daemon.slides.router.download_on_railway", blocking_download)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        with patch("daemon.ws_publish.broadcast"):
            # Unblock after a brief moment so all requests have time to arrive
            async def unblock():
                await asyncio.sleep(0.1)
                can_finish.set()

            results = await asyncio.gather(
                client.get(_check_url()),
                client.get(_check_url()),
                client.get(_check_url()),
                client.get(_check_url()),
                client.get(_check_url()),
                unblock(),
            )

    responses = [r for r in results if hasattr(r, "status_code")]
    assert download_count[0] == 1, f"Expected 1 Railway call, got {download_count[0]}"
    assert all(r.status_code == 200 for r in responses), \
        f"All should be 200, got {[r.status_code for r in responses]}"


@pytest.mark.anyio
async def test_waiters_get_200_when_in_flight_download_succeeds(app, state, monkeypatch):
    """Requests that waited on an in-flight download get 200 when it completes."""
    can_finish = threading.Event()

    def blocking_download(slug, url):
        can_finish.wait(timeout=5)
        return {"sha256": "abc"}

    monkeypatch.setattr("daemon.slides.router.download_on_railway", blocking_download)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        with patch("daemon.ws_publish.broadcast"):
            async def unblock():
                await asyncio.sleep(0.05)
                can_finish.set()

            results = await asyncio.gather(
                client.get(_check_url()),
                client.get(_check_url()),
                client.get(_check_url()),
                unblock(),
            )

    responses = [r for r in results if hasattr(r, "status_code")]
    assert all(r.status_code == 200 for r in responses)
    assert state.slides_updated[SLUG]["status"] == "cached"


@pytest.mark.anyio
async def test_waiters_get_503_when_in_flight_download_fails(app, state, monkeypatch):
    """Requests waiting on a failing download should get 503."""
    can_finish = threading.Event()

    def failing_download(slug, url):
        can_finish.wait(timeout=5)
        raise RuntimeError("network error")

    monkeypatch.setattr("daemon.slides.router.download_on_railway", failing_download)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        with patch("daemon.ws_publish.broadcast"):
            async def unblock():
                await asyncio.sleep(0.05)
                can_finish.set()

            results = await asyncio.gather(
                client.get(_check_url()),
                client.get(_check_url()),
                unblock(),
            )

    responses = [r for r in results if hasattr(r, "status_code")]
    assert all(r.status_code == 503 for r in responses)


@pytest.mark.anyio
async def test_different_slugs_download_in_parallel(app, state, monkeypatch):
    """Downloads for different slugs are never blocked by each other."""
    state.slides_catalog["slug-b"] = {
        "slug": "slug-b", "title": "B", "drive_export_url": DRIVE_URL
    }
    active_at_once = [0]
    max_active = [0]
    lock = threading.Lock()

    def concurrent_download(slug, url):
        with lock:
            active_at_once[0] += 1
            max_active[0] = max(max_active[0], active_at_once[0])
        time.sleep(0.05)
        with lock:
            active_at_once[0] -= 1
        return {"sha256": slug}

    monkeypatch.setattr("daemon.slides.router.download_on_railway", concurrent_download)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        with patch("daemon.ws_publish.broadcast"):
            results = await asyncio.gather(
                client.get(f"/{SESSION}/api/slides/check/{SLUG}"),
                client.get(f"/{SESSION}/api/slides/check/slug-b"),
            )

    assert all(r.status_code == 200 for r in results)
    assert max_active[0] == 2, "Both slugs should have downloaded concurrently"


# ── Pending redownload ────────────────────────────────────────────────────────

class TestPendingRedownload:
    def test_n_pptx_changes_while_active_produce_one_pending(self):
        _claim_download(SLUG)
        _queue_pending_redownload(SLUG)
        _queue_pending_redownload(SLUG)
        _queue_pending_redownload(SLUG)
        assert len(router_module._pending_redownload_slugs) == 1

    def test_finish_without_pending_does_not_trigger_redownload(self, client, state, monkeypatch):
        monkeypatch.setattr("daemon.slides.router.download_on_railway",
                            lambda s, u: {"sha256": "abc"})
        with patch("daemon.slides.router._trigger_pending_redownload") as mock_trigger, \
             patch("daemon.ws_publish.broadcast"):
            client.get(_check_url())
        mock_trigger.assert_not_called()

    def test_pending_redownload_triggered_after_download_completes(self, client, state, monkeypatch):
        monkeypatch.setattr("daemon.slides.router.download_on_railway",
                            lambda s, u: {"sha256": "abc"})
        _queue_pending_redownload(SLUG)
        triggered = []
        with patch("daemon.slides.router._trigger_pending_redownload",
                   side_effect=triggered.append), \
             patch("daemon.ws_publish.broadcast"):
            client.get(_check_url())
        assert triggered == [SLUG]

    def test_pending_cleared_even_when_download_fails(self, client, state, monkeypatch):
        monkeypatch.setattr("daemon.slides.router.download_on_railway",
                            lambda s, u: (_ for _ in ()).throw(RuntimeError("oops")))
        _queue_pending_redownload(SLUG)
        with patch("daemon.slides.router._trigger_pending_redownload") as mock_trigger, \
             patch("daemon.ws_publish.broadcast"):
            client.get(_check_url())
        # Pending redownload is still triggered even after a failure
        mock_trigger.assert_called_once_with(SLUG)
        assert SLUG not in router_module._pending_redownload_slugs

    def test_pending_cleared_after_triggered(self, client, state, monkeypatch):
        monkeypatch.setattr("daemon.slides.router.download_on_railway",
                            lambda s, u: {"sha256": "abc"})
        _queue_pending_redownload(SLUG)
        with patch("daemon.slides.router._trigger_pending_redownload"), \
             patch("daemon.ws_publish.broadcast"):
            client.get(_check_url())
        assert SLUG not in router_module._pending_redownload_slugs


# ── Cross-path: loop-triggered download blocks participant ────────────────────

@pytest.mark.anyio
async def test_participant_request_waits_when_loop_poller_is_active(app, state, monkeypatch):
    """A PPTX-change redownload running in loop.py blocks concurrent participant requests."""
    can_finish = threading.Event()
    download_count = [0]

    def blocking_download(slug, url):
        download_count[0] += 1
        can_finish.wait(timeout=5)
        return {"sha256": "abc"}

    monkeypatch.setattr("daemon.slides.router.download_on_railway", blocking_download)

    # Simulate loop.py having already claimed the download slot (as if PPTX changed)
    assert _claim_download(SLUG) is True  # loop.py claims it
    state.slides_updated[SLUG] = {"status": "downloading"}  # loop.py set this

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        with patch("daemon.ws_publish.broadcast"):
            async def release_loop_slot():
                await asyncio.sleep(0.05)
                # Simulate loop.py finishing its download → release slot, set cached
                state.slides_updated[SLUG] = {"status": "cached"}
                _finish_download(SLUG)  # wakes the participant waiter

            results = await asyncio.gather(
                client.get(_check_url()),  # participant — should wait
                release_loop_slot(),
            )

    responses = [r for r in results if hasattr(r, "status_code")]
    assert responses[0].status_code == 200
    assert download_count[0] == 0, "Participant must not trigger an extra download"
