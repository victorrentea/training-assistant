"""Tests for the Victor Effects HTTP client.

Everything here is best-effort by design: the Mac apps are allowed to be down,
and a daemon that raises because a soundboard is missing would take a workshop
with it. So every test asserts a *value*, never an exception.
"""
from unittest.mock import MagicMock, patch

from daemon import effects_client


def _response(status=200, json_body=None, content=b"", content_type="application/json"):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body if json_body is not None else {}
    r.content = content
    r.headers = {"content-type": content_type}
    return r


class TestPressTile:
    def test_press_calls_the_press_route_with_the_number(self):
        with patch("httpx.get", return_value=_response(json_body={"ok": True, "n": 69})) as g:
            assert effects_client.press_tile(69) is True
        assert g.call_args[0][0] == f"{effects_client.EFFECTS_BASE_URL}/press/69"

    def test_a_body_saying_not_ok_is_a_failure_even_at_200(self):
        """The press route reports an unknown tile in the body, not the status."""
        body = {"ok": False, "n": 999, "reason": "unknown-tile"}
        with patch("httpx.get", return_value=_response(json_body=body)):
            assert effects_client.press_tile(999) is False

    def test_a_transport_error_is_a_failure_not_an_exception(self):
        with patch("httpx.get", side_effect=OSError("connection refused")):
            assert effects_client.press_tile(69) is False

    def test_a_non_200_is_a_failure(self):
        with patch("httpx.get", return_value=_response(status=503)):
            assert effects_client.press_tile(69) is False


class TestFetchTiles:
    def test_returns_the_tiles_array(self):
        body = {"columns": 13, "tiles": [{"n": 69, "asset": "69_scream_ghost.mp3",
                                          "image": "tiles/sfx_69.jpg", "effect": "wazzup"}]}
        with patch("httpx.get", return_value=_response(json_body=body)):
            tiles = effects_client.fetch_tiles()
        assert tiles == body["tiles"]

    def test_returns_none_when_the_effects_app_is_down(self):
        with patch("httpx.get", side_effect=OSError("connection refused")):
            assert effects_client.fetch_tiles() is None

    def test_returns_none_when_the_body_has_no_tiles(self):
        with patch("httpx.get", return_value=_response(json_body={"error": "no tiles.json"})):
            assert effects_client.fetch_tiles() is None


class TestIsUp:
    def test_reads_effects_up_from_the_merged_ping(self):
        with patch("httpx.get", return_value=_response(json_body={"ok": True, "effectsUp": True})):
            assert effects_client.is_up() is True

    def test_addons_alive_but_effects_down_is_not_up(self):
        with patch("httpx.get", return_value=_response(json_body={"ok": True, "effectsUp": False})):
            assert effects_client.is_up() is False

    def test_unreachable_is_not_up(self):
        with patch("httpx.get", side_effect=OSError("connection refused")):
            assert effects_client.is_up() is False


class TestFetchTileImage:
    def test_returns_body_and_content_type(self):
        r = _response(content=b"\xff\xd8jpeg", content_type="image/jpeg")
        with patch("httpx.get", return_value=r):
            assert effects_client.fetch_tile_image("tiles/sfx_69.jpg") == (b"\xff\xd8jpeg", "image/jpeg")

    def test_returns_none_when_missing(self):
        with patch("httpx.get", return_value=_response(status=404)):
            assert effects_client.fetch_tile_image("tiles/nope.jpg") is None
