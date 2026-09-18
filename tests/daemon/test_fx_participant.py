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


PID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def roster():
    """Empty roster per test — `participant_state` is a module-level singleton,
    so a name left behind would silently name the next test's presser."""
    participant_state.participant_names.pop(PID, None)
    participant_state.anonymous_pids.discard(PID)
    yield
    participant_state.participant_names.pop(PID, None)
    participant_state.anonymous_pids.discard(PID)


@pytest.fixture(autouse=True)
def fx_state():
    participant_state.fx_enabled = True
    participant_state.fx_token = TOKEN
    participant_state.fx_tile_n = 69
    participant_state.fx_cooldown_seconds = 10
    participant_state.fx_last_fired_at = None
    participant_state.fx_last_fired_mono = None
    participant_state.fx_last_press_ok = None
    yield
    participant_state.fx_enabled = False
    participant_state.fx_token = None
    participant_state.fx_last_fired_mono = None
    participant_state.fx_last_press_ok = None


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


class TestHostileTokens:
    """A wrong token must be a flat 404 regardless of what the URL contains —
    never a 500. This is not merely defensive: a second, pre-existing Railway
    route (`/{session_id}/api/participant/fx/...`) relays whatever bytes a
    caller sends straight through to `_check_token`, unfiltered by the
    token-alphabet-anchored `/fx/{token}` regex that guards the first route.
    A 500 here is worse than an unhelpful 404 — it tells a prober their input
    broke something, which is the one thing this feature promises never to say.

    NUL and newline are sent percent-encoded (%00, %0A): those are the bytes
    a real client puts on the wire, and Starlette decodes them into the
    literal characters before routing ever runs. Handing the raw control
    character to the test client itself would just be rejected by httpx's
    own URL parser — that would test httpx, not this endpoint.
    """

    HOSTILE_TOKENS = [
        pytest.param("ĂÎȘ", id="non-ascii"),
        pytest.param("🎉🎉🎉", id="emoji"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace"),
        pytest.param("a" * 10_000, id="very-long"),
        pytest.param("abc%00def", id="nul-byte"),
        pytest.param("abc%0Adef", id="newline"),
        pytest.param("z" * len(TOKEN), id="correct-length-but-wrong"),
    ]

    @pytest.mark.parametrize("token", HOSTILE_TOKENS)
    def test_the_page_is_never_a_5xx_and_always_a_404(self, client, token):
        assert client.get(f"/api/participant/fx/{token}").status_code == 404

    @pytest.mark.parametrize("token", HOSTILE_TOKENS)
    def test_info_is_never_a_5xx_and_always_a_404(self, client, token):
        assert client.get(f"/api/participant/fx/{token}/info").status_code == 404

    @pytest.mark.parametrize("token", HOSTILE_TOKENS)
    def test_fire_is_never_a_5xx_and_presses_nothing(self, client, token):
        with patch("daemon.fx.router.effects_client.press_tile") as press:
            r = client.post(f"/api/participant/fx/{token}/fire")
        assert r.status_code == 404
        press.assert_not_called()


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

    def test_a_failed_press_marks_the_next_info_read_as_not_reachable_even_if_the_ping_is_up(self, client):
        """The bug this guards: a ping can succeed while the Mac apps lack the
        /press/<n> route a press needs. /info must not tell the page a press
        would work right after one just proved it wouldn't."""
        with patch("daemon.fx.router.effects_client.press_tile", return_value=False):
            client.post(f"/api/participant/fx/{TOKEN}/fire")
        with patch("daemon.fx.router.effects_client.is_up", return_value=True):
            r = client.get(f"/api/participant/fx/{TOKEN}/info")
        assert r.json()["effects_up"] is False


class TestDesktopAnnouncement:
    """The trainer's desktop tab (`fx_fired` over the addons WS bridge).

    The host badge already flashes, but during a workshop the host panel is
    behind the slides — the tab is the only surface the trainer actually sees,
    so it has to follow the press exactly: name the presser when the press
    lands, stay silent when it doesn't, and never be able to fail the press.
    """

    def test_a_successful_press_names_the_presser(self, client):
        participant_state.participant_names[PID] = "Ana Pop"
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True), \
             patch("daemon.addon_bridge_client.send_fx_fired") as announce:
            client.post(f"/api/participant/fx/{TOKEN}/fire",
                        headers={"X-Participant-ID": PID})
        announce.assert_called_once_with("Ana Pop", False)

    def test_an_anonymous_participant_is_flagged_not_hidden(self, client):
        participant_state.participant_names[PID] = "Grumpy Otter"
        participant_state.anonymous_pids.add(PID)
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True), \
             patch("daemon.addon_bridge_client.send_fx_fired") as announce:
            client.post(f"/api/participant/fx/{TOKEN}/fire",
                        headers={"X-Participant-ID": PID})
        announce.assert_called_once_with("Grumpy Otter", True)

    def test_a_press_with_no_participant_header_announces_someone(self, client):
        """The link opened on a phone that never joined the workshop. It still
        fires, and the tab still shows — just saying "Someone"."""
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True), \
             patch("daemon.addon_bridge_client.send_fx_fired") as announce:
            r = client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert r.json()["fired"] is True
        announce.assert_called_once_with("Someone", False)

    def test_an_unknown_participant_id_never_leaks_onto_the_screen(self, client):
        """The regression this guards: a raw UUID on the trainer's banner, in a
        room where that banner is on the projector."""
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True), \
             patch("daemon.addon_bridge_client.send_fx_fired") as announce:
            r = client.post(f"/api/participant/fx/{TOKEN}/fire",
                            headers={"X-Participant-ID": PID})
        caller = announce.call_args.args[0]
        assert caller == "Someone"
        # Neither wire may carry it: the overlay tab and the host badge are both
        # shown in the room the pid's owner is sitting in.
        assert PID not in caller
        assert PID not in r.text

    def test_a_blank_name_resolves_to_someone(self, client):
        participant_state.participant_names[PID] = "   "
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True), \
             patch("daemon.addon_bridge_client.send_fx_fired") as announce:
            client.post(f"/api/participant/fx/{TOKEN}/fire",
                        headers={"X-Participant-ID": PID})
        assert announce.call_args.args[0] == "Someone"

    def test_a_refused_press_announces_nothing(self, client):
        """Disabled, cooling, no-tile and effects-down all mean the room heard
        nothing — so the trainer must be told nothing."""
        participant_state.fx_enabled = False
        with patch("daemon.addon_bridge_client.send_fx_fired") as announce:
            client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert announce.call_count == 0

        participant_state.fx_enabled = True
        with patch("daemon.fx.router.effects_client.press_tile", return_value=False), \
             patch("daemon.addon_bridge_client.send_fx_fired") as announce:
            client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert announce.call_count == 0

    def test_a_closed_overlay_does_not_fail_the_press(self, client):
        """`send_fx_fired` returns False when the overlay isn't connected — the
        participant must still be told the press worked."""
        with patch("daemon.fx.router.effects_client.press_tile", return_value=True), \
             patch("daemon.addon_bridge_client.send_fx_fired", return_value=False):
            r = client.post(f"/api/participant/fx/{TOKEN}/fire")
        assert r.json()["fired"] is True


class TestInfo:
    def test_effects_up_is_true_by_default_when_the_ping_is_up_and_no_press_has_failed(self, client):
        with patch("daemon.fx.router.effects_client.is_up", return_value=True):
            r = client.get(f"/api/participant/fx/{TOKEN}/info")
        assert r.json()["effects_up"] is True

    def test_effects_up_is_false_when_the_ping_itself_is_down_regardless_of_press_history(self, client):
        with patch("daemon.fx.router.effects_client.is_up", return_value=False):
            r = client.get(f"/api/participant/fx/{TOKEN}/info")
        assert r.json()["effects_up"] is False

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

    def test_the_body_has_the_elements_the_page_cannot_work_without(self, client):
        """200 + text/html is not proof the page works: fx.html once shipped
        with a JS syntax error that killed its whole script and still passed
        exactly this envelope check (see tests/frontend/test_inline_script_
        syntax.py for the guard that now catches the script itself). This
        asserts on the markup and wiring the script depends on, so a change
        that drops the button, its id, or the script that drives it fails
        here too."""
        body = client.get(f"/api/participant/fx/{TOKEN}").text
        assert 'id="fire"' in body
        assert 'id="status"' in body
        # The effect's name is rendered inside the button itself, not in a
        # separate heading — the button is the only place it appears.
        assert 'id="num"' in body
        assert "getElementById('fire')" in body
        assert "/info" in body
        assert "/fire" in body


class TestLabels:
    def test_a_label_is_derived_from_the_asset_filename(self):
        from daemon.fx.router import tile_label
        assert tile_label(TILE_69) == "scream ghost"

    def test_an_explicit_label_wins(self):
        from daemon.fx.router import tile_label
        assert tile_label({"n": 1, "asset": "01_baby.mp3", "label": "Baby"}) == "Baby"
