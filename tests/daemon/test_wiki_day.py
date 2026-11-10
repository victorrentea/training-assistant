"""The workshop days the trainer shows on the wiki graph: broadcast live, kept in the snapshot."""
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
    misc_state.wiki_days = []
    yield
    misc_state.wiki_days = []


def _tick(*days):
    return _client().post("/wiki/day", json={"days": list(days)})


def test_ticking_days_is_broadcast_to_participants():
    with patch.object(misc_router, "broadcast") as broadcast:
        resp = _tick(2)

    assert resp.status_code == 200
    assert resp.json() == {"days": [2]}
    msg = broadcast.call_args.args[0]
    assert isinstance(msg, WikiDayMsg)
    assert msg.model_dump() == {"type": "wiki_day", "days": [2]}


def test_days_come_back_sorted_and_once():
    with patch.object(misc_router, "broadcast"):
        resp = _tick(2, 1, 2)
    assert resp.json() == {"days": [1, 2]}


def test_no_day_ticked_shows_every_day():
    with patch.object(misc_router, "broadcast") as broadcast:
        _tick(1)
        resp = _tick()

    assert resp.json() == {"days": []}
    assert broadcast.call_args.args[0].days == []
    assert _client().get("/api/participant/wiki/day").json() == {"days": []}


def test_a_wiki_in_a_tab_of_its_own_reads_the_days():
    with patch.object(misc_router, "broadcast"):
        _tick(2)
    assert _client().get("/api/participant/wiki/day").json() == {"days": [2]}


@pytest.mark.parametrize("day", [0, -1, 32, "two", 1.5])
def test_a_day_is_a_small_positive_number(day):
    with patch.object(misc_router, "broadcast") as broadcast:
        resp = _tick(day)
    assert resp.status_code == 422
    broadcast.assert_not_called()


def test_the_participant_state_carries_the_days():
    with patch.object(misc_router, "broadcast"):
        _tick(1)
    resp = _client().get("/api/participant/state", headers={"X-Participant-ID": "p1"})
    assert resp.status_code == 200
    assert resp.json()["wiki_days"] == [1]


def test_the_days_survive_a_daemon_restart_through_the_session_snapshot():
    from daemon.__main__ import _build_runtime_session_snapshot

    misc_state.wiki_days = [2]
    snapshot = _build_runtime_session_snapshot(session_name="s")
    misc_state.wiki_days = []  # the restart: nothing in memory
    misc_state.sync_from_restore(snapshot)
    assert misc_state.wiki_days == [2]


def test_a_new_session_shows_every_day():
    misc_state.wiki_days = [2]
    misc_state.reset_for_new_session()
    assert misc_state.wiki_days == []
