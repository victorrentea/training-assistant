"""Tests for the public half of the FX button.

This is the only part of the feature reachable from the internet, so the tests
are mostly about refusal: someone who was never granted, someone whose grant
was taken back, a closed master switch, a held-down finger, and a Mac whose
soundboard is not running.

The access model is a *grant*, so the question these tests keep asking is the
one the old secret link could never answer: does the server care who is
pressing, or only that someone is?
"""
import pytest
from unittest.mock import patch
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.fx.router import participant_router
from daemon.participant.state import participant_state

PID = "11111111-2222-3333-4444-555555555555"
OTHER = "99999999-8888-7777-6666-555555555555"
TILE_69 = {"n": 69, "asset": "69_scream_ghost.mp3",
           "image": "tiles/sfx_69_scream_ghost.jpg", "effect": "wazzup"}


@pytest.fixture(autouse=True)
def fx_state():
    """`participant_state` is a module-level singleton, so every knob this
    feature owns is set AND torn down here — a grant left behind would arm the
    next test's stranger."""
    participant_state.fx_enabled = True
    participant_state.fx_granted_pids = {PID}
    participant_state.fx_press_counts = {}
    participant_state.fx_tile_n = 69
    participant_state.fx_cooldown_seconds = 10
    participant_state.fx_last_fired_at = None
    participant_state.fx_last_fired_mono = None
    participant_state.fx_last_press_ok = None
    participant_state.participant_names[PID] = "Ana Pop"
    yield
    participant_state.fx_enabled = False
    participant_state.fx_granted_pids.clear()
    participant_state.fx_press_counts.clear()
    participant_state.fx_last_fired_mono = None
    participant_state.fx_last_press_ok = None
    participant_state.participant_names.pop(PID, None)
    participant_state.participant_names.pop(OTHER, None)
    participant_state.anonymous_pids.discard(PID)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def catalog():
    with patch("daemon.fx.router.effects_client.fetch_tiles", return_value=[TILE_69]):
        yield


@pytest.fixture(autouse=True)
def never_press_the_real_mac():
    """No test may reach the soundboard on 127.0.0.1:55123.

    It is a real machine, often in a real room: an unmocked `press_tile` in a
    test run on the trainer's laptop plays an actual sound at actual volume in
    front of actual people. (It did, once, while this file was being written.)
    So the default is patched here for every test, and a test that cares about
    the outcome re-patches it locally — an inner `patch` wins over this one.
    """
    with patch("daemon.fx.router.effects_client.press_tile", return_value=True):
        yield


@pytest.fixture(autouse=True)
def quiet_broadcast():
    """The fire path broadcasts a cooling frame; no WS client exists in a unit
    test, and ws_publish would silently no-op — patch it so the assertions can
    see it instead."""
    with patch("daemon.ws_publish.broadcast") as b:
        yield b


def _hdr(pid):
    return {"X-Participant-ID": pid}


class TestGrantIsTheAccessCheck:
    def test_a_granted_participant_can_fire(self, client):
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True) as press:
            r = client.post("/api/participant/fx/fire", headers=_hdr(PID))
        assert r.json()["fired"] is True
        press.assert_called_once_with(69)

    def test_a_stranger_is_refused_without_pressing(self, client):
        """The whole point of the model: the button is not hidden, it is denied."""
        with patch("daemon.fx.router.effects_client.press_tile") as press:
            r = client.post("/api/participant/fx/fire", headers=_hdr(OTHER))
        assert r.json() == {"fired": False, "reason": "not-granted", "ready_in_seconds": 0}
        press.assert_not_called()

    def test_a_revoked_participant_is_refused(self, client):
        participant_state.fx_granted_pids.discard(PID)
        with patch("daemon.fx.router.effects_client.press_tile") as press:
            r = client.post("/api/participant/fx/fire", headers=_hdr(PID))
        assert r.json()["reason"] == "not-granted"
        press.assert_not_called()

    def test_no_header_at_all_is_a_400_not_a_press(self, client):
        with patch("daemon.fx.router.effects_client.press_tile") as press:
            r = client.post("/api/participant/fx/fire")
        assert r.status_code == 400
        press.assert_not_called()

    def test_an_empty_header_is_not_a_grant(self, client):
        """Guard the falsy-membership trap: `"" in set()` must never pass, and
        an empty grant set must never make everyone a holder."""
        participant_state.fx_granted_pids.clear()
        with patch("daemon.fx.router.effects_client.press_tile") as press:
            r = client.post("/api/participant/fx/fire", headers=_hdr(""))
        assert r.status_code == 400
        press.assert_not_called()

    def test_a_stranger_cannot_tell_an_armed_session_from_a_disarmed_one(self, client):
        """`not-granted` is returned before the master switch is even read, so
        the refusal carries no information about the room."""
        participant_state.fx_enabled = False
        armed_off = client.post("/api/participant/fx/fire", headers=_hdr(OTHER)).json()
        participant_state.fx_enabled = True
        armed_on = client.post("/api/participant/fx/fire", headers=_hdr(OTHER)).json()
        assert armed_off == armed_on == {"fired": False, "reason": "not-granted",
                                         "ready_in_seconds": 0}


class TestInfoIsPerCaller:
    def test_info_tells_a_holder_they_hold_it(self, client):
        r = client.get("/api/participant/fx/info", headers=_hdr(PID))
        assert r.json()["granted"] is True
        assert r.json()["label"] == "scream ghost"

    def test_info_tells_a_stranger_they_do_not(self, client):
        assert client.get("/api/participant/fx/info", headers=_hdr(OTHER)).json()["granted"] is False

    def test_info_without_a_header_is_not_granted(self, client):
        """Reachable from the internet with no identity — it must answer, and
        the answer must be no."""
        r = client.get("/api/participant/fx/info")
        assert r.status_code == 200
        assert r.json()["granted"] is False

    def test_info_never_names_another_participant(self, client):
        """It is a participant-facing endpoint: it may describe the caller's own
        access and nothing about anyone else's."""
        body = client.get("/api/participant/fx/info", headers=_hdr(PID)).text
        assert OTHER not in body and PID not in body and "Ana Pop" not in body


class TestBrakes:
    def test_a_closed_switch_refuses_a_holder_without_pressing(self, client):
        participant_state.fx_enabled = False
        with patch("daemon.fx.router.effects_client.press_tile") as press:
            r = client.post("/api/participant/fx/fire", headers=_hdr(PID))
        assert r.json() == {"fired": False, "reason": "disabled", "ready_in_seconds": 0}
        press.assert_not_called()

    def test_the_cooldown_is_shared_by_the_whole_room(self, client):
        """One lever: a second holder pressing inside the window is refused too.
        With grant-all a click away, a per-person cooldown would let twenty
        people fire twenty sounds inside one window."""
        participant_state.fx_granted_pids.add(OTHER)
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True) as press:
            client.post("/api/participant/fx/fire", headers=_hdr(PID))
            r = client.post("/api/participant/fx/fire", headers=_hdr(OTHER))
        assert r.json()["fired"] is False
        assert r.json()["reason"] == "cooling"
        assert 0 < r.json()["ready_in_seconds"] <= 10
        assert press.call_count == 1

    def test_the_cooldown_expires(self, client):
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True) as press:
            client.post("/api/participant/fx/fire", headers=_hdr(PID))
            # Pretend the last press was 11 seconds ago on the monotonic clock.
            participant_state.fx_last_fired_mono -= 11
            r = client.post("/api/participant/fx/fire", headers=_hdr(PID))
        assert r.json()["fired"] is True
        assert press.call_count == 2

    def test_a_zero_cooldown_allows_back_to_back_presses(self, client):
        participant_state.fx_cooldown_seconds = 0
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True) as press:
            client.post("/api/participant/fx/fire", headers=_hdr(PID))
            r = client.post("/api/participant/fx/fire", headers=_hdr(PID))
        assert r.json()["fired"] is True
        assert press.call_count == 2

    def test_an_unknown_tile_is_refused_without_pressing(self, client):
        participant_state.fx_tile_n = 999
        with patch("daemon.fx.router.effects_client.press_tile") as press:
            r = client.post("/api/participant/fx/fire", headers=_hdr(PID))
        assert r.json()["reason"] == "no-tile"
        press.assert_not_called()

    def test_a_failed_press_reports_effects_down_and_does_not_start_a_cooldown(self, client):
        """A press that never happened must not lock the room for ten seconds."""
        with patch("daemon.fx.router.effects_client.press_tile", return_value=False):
            r = client.post("/api/participant/fx/fire", headers=_hdr(PID))
        assert r.json()["reason"] == "effects-down"
        assert participant_state.fx_last_fired_mono is None

    def test_a_failed_press_marks_the_next_info_read_as_not_reachable_even_if_the_ping_is_up(self, client):
        """The bug this guards: a ping can succeed while the Mac apps lack the
        /press/<n> route a press needs. /info must not tell the page a press
        would work right after one just proved it wouldn't."""
        with patch("daemon.fx.router.effects_client.press_tile", return_value=False):
            client.post("/api/participant/fx/fire", headers=_hdr(PID))
        with patch("daemon.fx.router.effects_client.is_up", return_value=True):
            r = client.get("/api/participant/fx/info", headers=_hdr(PID))
        assert r.json()["effects_up"] is False

    def test_effects_up_is_true_by_default_when_the_ping_is_up_and_no_press_has_failed(self, client):
        with patch("daemon.fx.router.effects_client.is_up", return_value=True):
            r = client.get("/api/participant/fx/info", headers=_hdr(PID))
        assert r.json()["effects_up"] is True


class TestPressCounts:
    def test_a_successful_press_counts(self, client):
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True):
            client.post("/api/participant/fx/fire", headers=_hdr(PID))
            participant_state.fx_last_fired_mono -= 11
            client.post("/api/participant/fx/fire", headers=_hdr(PID))
        assert participant_state.fx_press_counts[PID] == 2

    def test_counts_are_per_person(self, client):
        participant_state.fx_granted_pids.add(OTHER)
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True):
            client.post("/api/participant/fx/fire", headers=_hdr(PID))
            participant_state.fx_last_fired_mono -= 11
            client.post("/api/participant/fx/fire", headers=_hdr(OTHER))
        assert participant_state.fx_press_counts == {PID: 1, OTHER: 1}

    def test_a_refused_press_counts_for_nobody(self, client):
        """Counters answer "who is leaning on this". A press the room never
        heard is not someone leaning on it — whichever brake stopped it."""
        # Soundboard down.
        with patch("daemon.fx.router.effects_client.press_tile", return_value=False):
            client.post("/api/participant/fx/fire", headers=_hdr(PID))
        # Never granted.
        client.post("/api/participant/fx/fire", headers=_hdr(OTHER))
        # Master switch off.
        participant_state.fx_enabled = False
        client.post("/api/participant/fx/fire", headers=_hdr(PID))
        # No tile.
        participant_state.fx_enabled = True
        participant_state.fx_tile_n = 999
        client.post("/api/participant/fx/fire", headers=_hdr(PID))
        assert participant_state.fx_press_counts == {}


class TestDesktopAnnouncement:
    """The trainer's desktop tab (`fx_fired` over the addons WS bridge).

    The host badge already flashes, but during a workshop the host panel is
    behind the slides — the tab is the only surface the trainer actually sees,
    so it has to follow the press exactly: name the presser when the press
    lands, stay silent when it doesn't, and never be able to fail the press.
    """

    def test_a_successful_press_names_the_presser(self, client):
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True), \
             patch("daemon.addon_bridge_client.send_fx_fired") as announce:
            client.post("/api/participant/fx/fire", headers=_hdr(PID))
        announce.assert_called_once_with("Ana Pop", False)

    def test_an_anonymous_participant_is_flagged_not_hidden(self, client):
        participant_state.participant_names[PID] = "Grumpy Otter"
        participant_state.anonymous_pids.add(PID)
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True), \
             patch("daemon.addon_bridge_client.send_fx_fired") as announce:
            client.post("/api/participant/fx/fire", headers=_hdr(PID))
        announce.assert_called_once_with("Grumpy Otter", True)

    def test_a_refused_press_announces_nothing(self, client):
        participant_state.fx_enabled = False
        with patch("daemon.addon_bridge_client.send_fx_fired") as announce:
            client.post("/api/participant/fx/fire", headers=_hdr(PID))
        assert announce.call_count == 0

        participant_state.fx_enabled = True
        with patch("daemon.fx.router.effects_client.press_tile", return_value=False), \
             patch("daemon.addon_bridge_client.send_fx_fired") as announce:
            client.post("/api/participant/fx/fire", headers=_hdr(PID))
        assert announce.call_count == 0

    def test_a_closed_overlay_does_not_fail_the_press(self, client):
        """`send_fx_fired` returns False when the overlay isn't connected — the
        participant must still be told the press worked."""
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True), \
             patch("daemon.addon_bridge_client.send_fx_fired", return_value=False):
            r = client.post("/api/participant/fx/fire", headers=_hdr(PID))
        assert r.json()["fired"] is True

    def test_a_granted_participant_with_no_name_never_shows_a_uuid(self, client):
        participant_state.participant_names.pop(PID, None)
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True), \
             patch("daemon.addon_bridge_client.send_fx_fired") as announce:
            client.post("/api/participant/fx/fire", headers=_hdr(PID))
        caller = announce.call_args.args[0]
        assert caller == "Someone"
        assert PID not in caller


class TestSharedCooldownBroadcast:
    def test_a_press_tells_the_whole_room_to_grey_out(self, client, quiet_broadcast):
        """One lever means one press has to disable everyone else's button —
        otherwise the other holders find out by pressing into it."""
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True):
            client.post("/api/participant/fx/fire", headers=_hdr(PID))
        sent = [c.args[0] for c in quiet_broadcast.call_args_list]
        cooling = [m for m in sent if m.type == "fx_cooling"]
        assert len(cooling) == 1
        assert cooling[0].ready_in_seconds == 10

    def test_that_broadcast_names_nobody(self, client, quiet_broadcast):
        """It goes to every participant, so it must not carry the presser's
        UUID or name — see test_broadcast_uuid_strip.py for the sweep."""
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True):
            client.post("/api/participant/fx/fire", headers=_hdr(PID))
        for msg in [c.args[0] for c in quiet_broadcast.call_args_list]:
            blob = msg.model_dump_json()
            assert PID not in blob and "Ana Pop" not in blob

    def test_a_refused_press_greys_out_nobody(self, client, quiet_broadcast):
        with patch("daemon.fx.router.effects_client.press_tile", return_value=False):
            client.post("/api/participant/fx/fire", headers=_hdr(PID))
        assert quiet_broadcast.call_count == 0
