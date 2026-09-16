"""Tests for the host's FX controls.

The host page is served over loopback, so there is no auth here — the tests are
about behaviour: the link is minted lazily, rotation invalidates the old one,
and the host's own Test button works precisely when the link is disarmed.
"""
import pytest
from unittest.mock import patch
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.fx.router import host_router, participant_router
from daemon.participant.state import participant_state

TILE_69 = {"n": 69, "asset": "69_scream_ghost.mp3",
           "image": "tiles/sfx_69_scream_ghost.jpg", "effect": "wazzup"}
TILE_1 = {"n": 1, "asset": "01_baby.mp3", "image": "tiles/sfx_01_baby.jpg"}


@pytest.fixture(autouse=True)
def fx_state():
    participant_state.fx_enabled = False
    participant_state.fx_token = None
    participant_state.fx_tile_n = 69
    participant_state.fx_cooldown_seconds = 10
    participant_state.fx_last_fired_at = None
    participant_state.fx_last_fired_mono = None
    participant_state.fx_last_press_ok = None
    yield
    participant_state.fx_enabled = False
    participant_state.fx_token = None
    participant_state.fx_last_press_ok = None


@pytest.fixture(autouse=True)
def no_persist():
    with patch("daemon.participant.state.ParticipantState.persist"):
        yield


@pytest.fixture(autouse=True)
def catalog():
    with patch("daemon.fx.router.effects_client.fetch_tiles", return_value=[TILE_1, TILE_69]), \
         patch("daemon.fx.router.effects_client.is_up", return_value=True):
        yield


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(host_router)
    app.include_router(participant_router)
    return TestClient(app)


class TestState:
    def test_the_first_read_mints_a_token(self, client):
        assert participant_state.fx_token is None
        body = client.get("/api/cur/host/fx/state").json()
        assert len(body["token"]) == 12
        assert participant_state.fx_token == body["token"]

    def test_a_second_read_keeps_the_same_token(self, client):
        first = client.get("/api/cur/host/fx/state").json()["token"]
        assert client.get("/api/cur/host/fx/state").json()["token"] == first

    def test_the_url_is_the_short_public_form(self, client):
        with patch.dict("os.environ", {"WORKSHOP_SERVER_URL": "https://interact.victorrentea.ro"}):
            body = client.get("/api/cur/host/fx/state").json()
        assert body["url"] == f"https://interact.victorrentea.ro/fx/{body['token']}"

    def test_it_names_the_selected_tile(self, client):
        body = client.get("/api/cur/host/fx/state").json()
        assert body["tile_n"] == 69
        assert body["tile_label"] == "scream ghost"
        assert body["effect"] == "wazzup"


class TestCatalog:
    def test_it_lists_every_tile_with_a_label(self, client):
        tiles = client.get("/api/cur/host/fx/catalog").json()["tiles"]
        assert [t["n"] for t in tiles] == [1, 69]
        assert tiles[1]["label"] == "scream ghost"

    def test_it_marks_which_tiles_animate_the_screen(self, client):
        tiles = client.get("/api/cur/host/fx/catalog").json()["tiles"]
        assert tiles[0]["has_effect"] is False
        assert tiles[1]["has_effect"] is True

    def test_a_missing_soundboard_is_an_empty_catalog_not_a_crash(self, client):
        with patch("daemon.fx.router.effects_client.fetch_tiles", return_value=None):
            r = client.get("/api/cur/host/fx/catalog")
        assert r.status_code == 200
        assert r.json()["tiles"] == []


class TestToggle:
    def test_it_flips_the_switch(self, client):
        assert client.post("/api/cur/host/fx/toggle").json()["enabled"] is True
        assert participant_state.fx_enabled is True
        assert client.post("/api/cur/host/fx/toggle").json()["enabled"] is False


class TestTile:
    def test_it_selects_a_tile_from_the_catalog(self, client):
        assert client.post("/api/cur/host/fx/tile", json={"n": 1}).json()["tile_n"] == 1
        assert participant_state.fx_tile_n == 1

    def test_a_tile_outside_the_catalog_is_refused(self, client):
        r = client.post("/api/cur/host/fx/tile", json={"n": 999})
        assert r.status_code == 404
        assert participant_state.fx_tile_n == 69


class TestCooldown:
    def test_it_sets_the_cooldown(self, client):
        assert client.post("/api/cur/host/fx/cooldown", json={"seconds": 30}).json()["cooldown_seconds"] == 30

    def test_a_negative_cooldown_is_rejected(self, client):
        assert client.post("/api/cur/host/fx/cooldown", json={"seconds": -1}).status_code == 422

    def test_an_absurd_cooldown_is_rejected(self, client):
        assert client.post("/api/cur/host/fx/cooldown", json={"seconds": 3600}).status_code == 422


class TestRotate:
    def test_rotation_changes_the_token(self, client):
        old = client.get("/api/cur/host/fx/state").json()["token"]
        new = client.post("/api/cur/host/fx/rotate").json()["token"]
        assert new != old

    def test_the_old_link_stops_working_immediately(self, client):
        old = client.get("/api/cur/host/fx/state").json()["token"]
        client.post("/api/cur/host/fx/rotate")
        assert client.post(f"/api/participant/fx/{old}/fire").status_code == 404


class TestHostTestButton:
    def test_it_fires_even_while_the_link_is_disarmed(self, client):
        """You test the wiring precisely when the link is not live."""
        assert participant_state.fx_enabled is False
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True) as press:
            r = client.post("/api/cur/host/fx/test")
        assert r.json()["fired"] is True
        press.assert_called_once_with(69)

    def test_it_ignores_the_cooldown(self, client):
        participant_state.fx_cooldown_seconds = 300
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True) as press:
            client.post("/api/cur/host/fx/test")
            r = client.post("/api/cur/host/fx/test")
        assert r.json()["fired"] is True
        assert press.call_count == 2

    def test_it_does_not_start_a_cooldown_for_the_room(self, client):
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True):
            client.post("/api/cur/host/fx/test")
        assert participant_state.fx_last_fired_mono is None

    def test_it_still_reports_a_closed_soundboard(self, client):
        with patch("daemon.fx.router.effects_client.press_tile", return_value=False):
            assert client.post("/api/cur/host/fx/test").json()["reason"] == "effects-down"

    def test_a_failed_test_marks_the_link_not_reachable_in_state(self, client):
        with patch("daemon.fx.router.effects_client.press_tile", return_value=False):
            client.post("/api/cur/host/fx/test")
        assert client.get("/api/cur/host/fx/state").json()["effects_up"] is False

    def test_a_later_successful_test_is_the_recovery_path(self, client):
        """Once a press has failed, /info won't trust the ping again on its own
        — a later real press (here, the host's Test button) is what clears it,
        which is how the trainer confirms the wiring before re-arming the room."""
        with patch("daemon.fx.router.effects_client.press_tile", return_value=False):
            client.post("/api/cur/host/fx/test")
        assert client.get("/api/cur/host/fx/state").json()["effects_up"] is False
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True):
            client.post("/api/cur/host/fx/test")
        assert client.get("/api/cur/host/fx/state").json()["effects_up"] is True
