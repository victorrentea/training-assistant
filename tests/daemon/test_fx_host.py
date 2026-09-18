"""Tests for the host's FX controls.

The host page is served over loopback, so there is no auth here — the tests are
about behaviour: who the grants reach, what survives a revoke, and the fact that
the host's own Test button works precisely when everything else is switched off.
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

ANA = "aaaaaaaa-0000-0000-0000-000000000001"
DAN = "dddddddd-0000-0000-0000-000000000002"


@pytest.fixture(autouse=True)
def fx_state():
    participant_state.fx_enabled = False
    participant_state.fx_granted_pids = set()
    participant_state.fx_press_counts = {}
    participant_state.fx_tile_n = 69
    participant_state.fx_cooldown_seconds = 10
    participant_state.fx_last_fired_at = None
    participant_state.fx_last_fired_mono = None
    participant_state.fx_last_press_ok = None
    participant_state.participant_names.update({ANA: "Ana Pop", DAN: "Dan"})
    yield
    participant_state.fx_enabled = False
    participant_state.fx_granted_pids.clear()
    participant_state.fx_press_counts.clear()
    participant_state.fx_last_press_ok = None
    for pid in (ANA, DAN):
        participant_state.participant_names.pop(pid, None)


@pytest.fixture(autouse=True)
def no_persist():
    with patch("daemon.participant.state.ParticipantState.persist"):
        yield


@pytest.fixture(autouse=True)
def quiet_broadcast():
    """Every host control that changes access broadcasts `fx_changed`; there is
    no WS client in a unit test, so patch it where the assertions can see it."""
    with patch("daemon.ws_publish.broadcast") as b:
        yield b


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
    def test_a_fresh_session_has_nobody_holding_it(self, client):
        body = client.get("/api/cur/host/fx/state").json()
        assert body["granted"] == []
        assert body["press_counts"] == {}

    def test_it_reports_the_grants_and_the_counters(self, client):
        """Host-only, so UUIDs belong here: the roster draws one toggle and one
        counter per row and needs a key for each."""
        participant_state.fx_granted_pids = {ANA}
        participant_state.fx_press_counts = {ANA: 3}
        body = client.get("/api/cur/host/fx/state").json()
        assert body["granted"] == [ANA]
        assert body["press_counts"] == {ANA: 3}

    def test_it_no_longer_carries_a_link(self, client):
        """The secret link is gone; nothing here should hand one back."""
        body = client.get("/api/cur/host/fx/state").json()
        assert "token" not in body and "url" not in body

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


class TestGrants:
    def test_granting_one_person_lets_exactly_that_person_press(self, client):
        client.post("/api/cur/host/fx/grant", json={"participant_id": ANA})
        assert participant_state.fx_granted_pids == {ANA}
        assert client.get("/api/participant/fx/info",
                          headers={"X-Participant-ID": ANA}).json()["granted"] is True
        assert client.get("/api/participant/fx/info",
                          headers={"X-Participant-ID": DAN}).json()["granted"] is False

    def test_granting_twice_is_not_two_grants(self, client):
        client.post("/api/cur/host/fx/grant", json={"participant_id": ANA})
        body = client.post("/api/cur/host/fx/grant", json={"participant_id": ANA}).json()
        assert body["granted"] == [ANA]

    def test_revoking_takes_the_button_away_immediately(self, client):
        client.post("/api/cur/host/fx/grant", json={"participant_id": ANA})
        client.post("/api/cur/host/fx/revoke", json={"participant_id": ANA})
        assert participant_state.fx_granted_pids == set()
        assert client.post("/api/participant/fx/fire",
                           headers={"X-Participant-ID": ANA}).json()["reason"] == "not-granted"

    def test_revoking_keeps_the_press_count(self, client):
        """The count is the session's record of what happened, not a property
        of the grant — re-granting someone must not wipe their history."""
        participant_state.fx_press_counts = {ANA: 4}
        client.post("/api/cur/host/fx/revoke", json={"participant_id": ANA})
        assert client.get("/api/cur/host/fx/state").json()["press_counts"] == {ANA: 4}

    def test_revoking_someone_who_never_held_it_is_not_an_error(self, client):
        assert client.post("/api/cur/host/fx/revoke", json={"participant_id": DAN}).status_code == 200

    def test_grant_all_reaches_the_whole_roster_not_just_who_is_online(self, client):
        """Someone who steps out and comes back would otherwise find their
        button gone for reasons nobody could explain."""
        body = client.post("/api/cur/host/fx/grant-all").json()
        assert set(body["granted"]) == {ANA, DAN}

    def test_revoke_all_is_the_panic_button(self, client):
        client.post("/api/cur/host/fx/grant-all")
        assert client.post("/api/cur/host/fx/revoke-all").json()["granted"] == []
        assert client.post("/api/participant/fx/fire",
                           headers={"X-Participant-ID": ANA}).json()["reason"] == "not-granted"

    def test_revoke_all_keeps_the_counters(self, client):
        participant_state.fx_press_counts = {ANA: 2, DAN: 7}
        client.post("/api/cur/host/fx/revoke-all")
        assert client.get("/api/cur/host/fx/state").json()["press_counts"] == {ANA: 2, DAN: 7}


class TestParticipantsAreToldToRecheck:
    """Every control that can change who holds the button has to wake the
    pages, or a grant is invisible until the holder reloads."""

    @pytest.mark.parametrize("call", [
        lambda c: c.post("/api/cur/host/fx/grant", json={"participant_id": ANA}),
        lambda c: c.post("/api/cur/host/fx/revoke", json={"participant_id": ANA}),
        lambda c: c.post("/api/cur/host/fx/grant-all"),
        lambda c: c.post("/api/cur/host/fx/revoke-all"),
        lambda c: c.post("/api/cur/host/fx/toggle"),
        lambda c: c.post("/api/cur/host/fx/tile", json={"n": 1}),
        lambda c: c.post("/api/cur/host/fx/cooldown", json={"seconds": 5}),
    ])
    def test_it_broadcasts_fx_changed(self, client, quiet_broadcast, call):
        call(client)
        types = [c.args[0].type for c in quiet_broadcast.call_args_list]
        assert "fx_changed" in types

    def test_that_broadcast_names_nobody(self, client, quiet_broadcast):
        """It reaches the whole room, so it cannot say who was granted — each
        page asks about itself instead."""
        client.post("/api/cur/host/fx/grant", json={"participant_id": ANA})
        for msg in [c.args[0] for c in quiet_broadcast.call_args_list]:
            blob = msg.model_dump_json()
            assert ANA not in blob and "Ana Pop" not in blob


class TestHostTestButton:
    def test_it_fires_even_while_disarmed_and_ungranted(self, client):
        """You test the wiring precisely when nothing else is live."""
        assert participant_state.fx_enabled is False
        assert participant_state.fx_granted_pids == set()
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

    def test_the_host_test_is_counted_against_nobody(self, client):
        """The counters answer "who is leaning on this", and the trainer
        checking his own soundboard is not an answer to that."""
        client.post("/api/cur/host/fx/test")
        assert participant_state.fx_press_counts == {}

    def test_a_failed_test_marks_it_not_reachable_in_state(self, client):
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
