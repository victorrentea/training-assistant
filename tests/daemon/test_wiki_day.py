"""The workshop day the trainer shows on the wiki graph: broadcast live, kept in the snapshot."""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.misc import router as misc_router
from daemon.misc.state import misc_state
from daemon.participant import router as participant_router
from daemon.ws_messages import WikiDayMsg


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(misc_router.local_router)
    app.include_router(participant_router.router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def every_day():
    misc_state.wiki_day = None
    yield
    misc_state.wiki_day = None


def _pick(day):
    return _client().post("/wiki/day", json={"day": day})


def test_picking_a_day_is_broadcast_to_participants():
    with patch.object(misc_router, "broadcast") as broadcast:
        resp = _pick(2)

    assert resp.status_code == 200
    assert resp.json() == {"day": 2}
    msg = broadcast.call_args.args[0]
    assert isinstance(msg, WikiDayMsg)
    assert msg.model_dump() == {"type": "wiki_day", "day": 2}


def test_none_shows_every_day_again():
    with patch.object(misc_router, "broadcast") as broadcast:
        _pick(1)
        resp = _pick(None)

    assert resp.json() == {"day": None}
    assert broadcast.call_args.args[0].day is None
    assert _client().get("/api/participant/wiki/day").json() == {"day": None}


def test_a_wiki_in_a_tab_of_its_own_reads_the_day():
    with patch.object(misc_router, "broadcast"):
        _pick(2)
    assert _client().get("/api/participant/wiki/day").json() == {"day": 2}


@pytest.mark.parametrize("day", [0, -1, 32, "two", 1.5])
def test_a_day_is_a_small_positive_number(day):
    with patch.object(misc_router, "broadcast") as broadcast:
        resp = _pick(day)
    assert resp.status_code == 422
    broadcast.assert_not_called()


def test_the_participant_state_carries_the_day():
    with patch.object(misc_router, "broadcast"):
        _pick(1)
    resp = _client().get("/api/participant/state", headers={"X-Participant-ID": "p1"})
    assert resp.status_code == 200
    assert resp.json()["wiki_day"] == 1


def test_the_day_survives_a_daemon_restart_through_the_session_snapshot():
    from daemon.__main__ import _build_runtime_session_snapshot

    misc_state.wiki_day = 2
    snapshot = _build_runtime_session_snapshot(session_name="s")
    misc_state.wiki_day = None  # the restart: nothing in memory
    misc_state.sync_from_restore(snapshot)
    assert misc_state.wiki_day == 2


def test_a_new_session_shows_every_day():
    misc_state.wiki_day = 2
    misc_state.reset_for_new_session()
    assert misc_state.wiki_day is None
