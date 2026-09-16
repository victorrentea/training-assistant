"""Tests for the Victor Effects HTTP client.

Everything here is best-effort by design: the Mac apps are allowed to be down,
and a daemon that raises because a soundboard is missing would take a workshop
with it. So every test asserts a *value*, never an exception.

The client's public functions are coroutines — they run `httpx.get` on a
worker thread via `asyncio.to_thread` so a slow or wedged Mac app never blocks
the daemon's event loop (see the module docstring in `effects_client.py`).
Tests still patch `httpx.get` directly; only the call site gains an `await`.
"""
from unittest.mock import MagicMock, patch

import pytest

from daemon import effects_client


pytestmark = pytest.mark.anyio


def _response(status=200, json_body=None, content=b"", content_type="application/json"):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body if json_body is not None else {}
    r.content = content
    r.headers = {"content-type": content_type}
    return r


@pytest.fixture(autouse=True)
def _reset_read_cache():
    """Reset the read cache so one test's response doesn't leak into the next."""
    effects_client._tiles_cache_at = None
    effects_client._tiles_cache_value = None
    effects_client._up_cache_at = None
    effects_client._up_cache_value = False
    yield


class TestPressTile:
    async def test_press_calls_the_press_route_with_the_number(self):
        with patch("httpx.get", return_value=_response(json_body={"ok": True, "n": 69})) as g:
            assert await effects_client.press_tile(69) is True
        assert g.call_args[0][0] == f"{effects_client.EFFECTS_BASE_URL}/press/69"

    async def test_a_body_saying_not_ok_is_a_failure_even_at_200(self):
        """The press route reports an unknown tile in the body, not the status."""
        body = {"ok": False, "n": 999, "reason": "unknown-tile"}
        with patch("httpx.get", return_value=_response(json_body=body)):
            assert await effects_client.press_tile(999) is False

    async def test_a_transport_error_is_a_failure_not_an_exception(self):
        with patch("httpx.get", side_effect=OSError("connection refused")):
            assert await effects_client.press_tile(69) is False

    async def test_a_non_200_is_a_failure(self):
        with patch("httpx.get", return_value=_response(status=503)):
            assert await effects_client.press_tile(69) is False

    async def test_press_is_never_cached(self):
        """Two presses in a row must both reach the Mac — a press is an
        action, not a read, so the short-lived read cache must not apply."""
        with patch("httpx.get", return_value=_response(json_body={"ok": True})) as g:
            await effects_client.press_tile(69)
            await effects_client.press_tile(69)
        assert g.call_count == 2


class TestFetchTiles:
    async def test_returns_the_tiles_array(self):
        body = {"columns": 13, "tiles": [{"n": 69, "asset": "69_scream_ghost.mp3",
                                          "image": "tiles/sfx_69.jpg", "effect": "wazzup"}]}
        with patch("httpx.get", return_value=_response(json_body=body)):
            tiles = await effects_client.fetch_tiles()
        assert tiles == body["tiles"]

    async def test_returns_none_when_the_effects_app_is_down(self):
        with patch("httpx.get", side_effect=OSError("connection refused")):
            assert await effects_client.fetch_tiles() is None

    async def test_returns_none_when_the_body_has_no_tiles(self):
        with patch("httpx.get", return_value=_response(json_body={"error": "no tiles.json"})):
            assert await effects_client.fetch_tiles() is None

    async def test_a_second_call_within_the_ttl_is_served_from_cache(self):
        body = {"tiles": [{"n": 1}]}
        with patch("httpx.get", return_value=_response(json_body=body)) as g:
            await effects_client.fetch_tiles()
            await effects_client.fetch_tiles()
        assert g.call_count == 1

    async def test_a_call_after_the_ttl_hits_the_network_again(self):
        body = {"tiles": [{"n": 1}]}
        with patch("httpx.get", return_value=_response(json_body=body)) as g:
            await effects_client.fetch_tiles()
            effects_client._tiles_cache_at -= effects_client._READ_CACHE_TTL + 0.1
            await effects_client.fetch_tiles()
        assert g.call_count == 2


class TestIsUp:
    async def test_reads_effects_up_from_the_merged_ping(self):
        with patch("httpx.get", return_value=_response(json_body={"ok": True, "effectsUp": True})):
            assert await effects_client.is_up() is True

    async def test_addons_alive_but_effects_down_is_not_up(self):
        with patch("httpx.get", return_value=_response(json_body={"ok": True, "effectsUp": False})):
            assert await effects_client.is_up() is False

    async def test_unreachable_is_not_up(self):
        with patch("httpx.get", side_effect=OSError("connection refused")):
            assert await effects_client.is_up() is False

    async def test_a_second_call_within_the_ttl_is_served_from_cache(self):
        with patch("httpx.get", return_value=_response(json_body={"effectsUp": True})) as g:
            await effects_client.is_up()
            await effects_client.is_up()
        assert g.call_count == 1
