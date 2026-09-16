"""Tests for the public half of the secret FX link.

This is the only part of the feature reachable from the internet, so the tests
are mostly about refusal: a wrong token, a closed switch, a held-down F5, and a
Mac whose soundboard is not running.
"""
import pytest
from unittest.mock import patch
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.fx.router import participant_router
from daemon.fx.token import FX_TOKEN_ALPHABET, FX_TOKEN_LEN, generate_fx_token
from daemon.participant.state import participant_state

TOKEN = "abc123def456"
TILE_69 = {"n": 69, "asset": "69_scream_ghost.mp3",
           "image": "tiles/sfx_69_scream_ghost.jpg", "effect": "wazzup"}


@pytest.fixture(autouse=True)
def fx_state():
    participant_state.fx_enabled = True
    participant_state.fx_token = TOKEN
    participant_state.fx_tile_n = 69
    participant_state.fx_cooldown_seconds = 10
    participant_state.fx_last_fired_at = None
    participant_state.fx_last_fired_mono = None
    yield
    participant_state.fx_enabled = False
    participant_state.fx_token = None
    participant_state.fx_last_fired_mono = None


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def catalog():
    with patch("daemon.fx.router.effects_client.fetch_tiles", return_value=[TILE_69]):
        yield


class TestToken:
    def test_the_alphabet_excludes_confusable_characters(self):
        for c in "oO0l":
            assert c not in FX_TOKEN_ALPHABET

    def test_a_token_is_twelve_characters_from_that_alphabet(self):
        t = generate_fx_token()
        assert len(t) == FX_TOKEN_LEN == 12
        assert set(t) <= set(FX_TOKEN_ALPHABET)

    def test_two_tokens_differ(self):
        assert generate_fx_token() != generate_fx_token()


class TestWrongToken:
    def test_the_page_is_a_flat_404(self, client):
        assert client.get("/api/participant/fx/wrongtoken12").status_code == 404

    def test_info_is_a_flat_404(self, client):
        assert client.get("/api/participant/fx/wrongtoken12/info").status_code == 404

    def test_fire_is_a_flat_404_and_presses_nothing(self, client):
        with patch("daemon.fx.router.effects_client.press_tile") as press:
            assert client.post("/api/participant/fx/wrongtoken12/fire").status_code == 404
        press.assert_not_called()

    def test_no_token_at_all_means_every_token_is_wrong(self, client):
        participant_state.fx_token = None
        assert client.post(f"/api/participant/fx/{TOKEN}/fire").status_code == 404


class TestFire:
    def test_the_happy_path_presses_the_selected_tile_once(self, client):
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True) as press:
            r = client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert r.status_code == 200
        assert r.json()["fired"] is True
        assert r.json()["reason"] == "ok"
        press.assert_called_once_with(69)

    def test_a_closed_switch_refuses_without_pressing(self, client):
        participant_state.fx_enabled = False
        with patch("daemon.fx.router.effects_client.press_tile") as press:
            r = client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert r.json() == {"fired": False, "reason": "disabled", "ready_in_seconds": 0}
        press.assert_not_called()

    def test_a_second_press_inside_the_cooldown_is_refused(self, client):
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True) as press:
            client.post(f"/api/participant/fx/{TOKEN}/fire")
            r = client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert r.json()["fired"] is False
        assert r.json()["reason"] == "cooling"
        assert 0 < r.json()["ready_in_seconds"] <= 10
        assert press.call_count == 1

    def test_the_cooldown_expires(self, client):
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True) as press:
            client.post(f"/api/participant/fx/{TOKEN}/fire")
            # Pretend the last press was 11 seconds ago on the monotonic clock.
            participant_state.fx_last_fired_mono -= 11
            r = client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert r.json()["fired"] is True
        assert press.call_count == 2

    def test_a_zero_cooldown_allows_back_to_back_presses(self, client):
        participant_state.fx_cooldown_seconds = 0
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True) as press:
            client.post(f"/api/participant/fx/{TOKEN}/fire")
            r = client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert r.json()["fired"] is True
        assert press.call_count == 2

    def test_an_unknown_tile_is_refused_without_pressing(self, client):
        participant_state.fx_tile_n = 999
        with patch("daemon.fx.router.effects_client.press_tile") as press:
            r = client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert r.json()["reason"] == "no-tile"
        press.assert_not_called()

    def test_a_failed_press_reports_effects_down_and_does_not_start_a_cooldown(self, client):
        """A press that never happened must not lock the button for ten seconds."""
        with patch("daemon.fx.router.effects_client.press_tile", return_value=False):
            r = client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert r.json()["reason"] == "effects-down"
        assert participant_state.fx_last_fired_mono is None


class TestInfo:
    def test_it_describes_the_selected_tile(self, client):
        with patch("daemon.fx.router.effects_client.is_up", return_value=True):
            r = client.get(f"/api/participant/fx/{TOKEN}/info")
        body = r.json()
        assert body["tile_n"] == 69
        assert body["label"] == "scream ghost"
        assert body["effect"] == "wazzup"
        assert body["enabled"] is True
        assert body["cooldown_seconds"] == 10
        assert body["ready_in_seconds"] == 0

    def test_it_reports_a_closed_switch_so_an_open_tab_catches_up(self, client):
        participant_state.fx_enabled = False
        with patch("daemon.fx.router.effects_client.is_up", return_value=True):
            r = client.get(f"/api/participant/fx/{TOKEN}/info")
        assert r.json()["enabled"] is False

    def test_tile_available_is_true_when_the_tile_is_in_the_catalog(self, client):
        with patch("daemon.fx.router.effects_client.is_up", return_value=True):
            r = client.get(f"/api/participant/fx/{TOKEN}/info")
        assert r.json()["tile_available"] is True

    def test_tile_available_is_false_when_the_tile_is_not_in_the_catalog(self, client):
        participant_state.fx_tile_n = 999  # A tile that does not exist
        with patch("daemon.fx.router.effects_client.is_up", return_value=True):
            r = client.get(f"/api/participant/fx/{TOKEN}/info")
        body = r.json()
        assert body["tile_available"] is False
        assert body["tile_n"] == 999
        assert body["label"] == "tile 999"  # Fallback label when tile not found


class TestPage:
    def test_the_page_is_html(self, client):
        r = client.get(f"/api/participant/fx/{TOKEN}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")


class TestLabels:
    def test_a_label_is_derived_from_the_asset_filename(self):
        from daemon.fx.router import tile_label
        assert tile_label(TILE_69) == "scream ghost"

    def test_an_explicit_label_wins(self):
        from daemon.fx.router import tile_label
        assert tile_label({"n": 1, "asset": "01_baby.mp3", "label": "Baby"}) == "Baby"
