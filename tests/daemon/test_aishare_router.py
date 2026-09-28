"""Tests for the AI-share slider activity (daemon/aishare)."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.aishare.router import host_router, participant_router
from daemon.aishare.state import AiShareState
from daemon.participant.state import ParticipantState


@pytest.fixture
def state():
    s = AiShareState()
    with patch("daemon.aishare.router.aishare_state", s):
        yield s


@pytest.fixture
def pstate():
    ps = ParticipantState()
    ps.participant_names.update({"u1": "Ana", "u2": "Bob"})
    with patch("daemon.aishare.router.participant_state", ps):
        yield ps


@pytest.fixture
def sent(state, pstate):
    """Collects every message broadcast to participants / notified to the host."""
    out = {"broadcast": [], "host": []}
    with patch("daemon.aishare.router.broadcast", side_effect=out["broadcast"].append), \
         patch("daemon.aishare.router.notify_host", new=AsyncMock(side_effect=out["host"].append)):
        yield out


@pytest.fixture
def client(sent):
    app = FastAPI()
    app.include_router(host_router)
    app.include_router(participant_router)
    return TestClient(app)


def _answer(client, pid, value):
    return client.post("/api/participant/aishare/value", json={"value": value},
                       headers={"X-Participant-ID": pid})


def _last(msgs, type_):
    return [m for m in msgs if m.type == type_][-1]


def test_start_routes_everyone_to_the_activity(client, pstate, sent):
    assert client.post("/api/cur/host/aishare/start").status_code == 204
    assert pstate.current_activity == "aishare"
    types = [m.type for m in sent["broadcast"]]
    assert types[:2] == ["activity_updated", "aishare_opened"]


def test_answer_rejected_before_start(client):
    assert _answer(client, "u1", 40).status_code == 409


def test_answer_out_of_range_rejected(client):
    client.post("/api/cur/host/aishare/start")
    assert _answer(client, "u1", 101).status_code == 422
    assert _answer(client, "u1", -1).status_code == 422


def test_answers_hidden_from_participants_until_revealed(client, sent):
    client.post("/api/cur/host/aishare/start")
    _answer(client, "u1", 80)
    _answer(client, "u2", 20)

    pax = _last(sent["broadcast"], "aishare_updated")
    assert pax.count == 2 and pax.points is None
    host = _last(sent["host"], "aishare_host_update")
    assert [(p.name, p.value) for p in host.points] == [("Bob", 20), ("Ana", 80)]

    client.post("/api/cur/host/aishare/reveal", json={"revealed": True})
    pax = _last(sent["broadcast"], "aishare_updated")
    assert [(p.name, p.value) for p in pax.points] == [("Bob", 20), ("Ana", 80)]


def test_last_answer_wins(client, state):
    client.post("/api/cur/host/aishare/start")
    _answer(client, "u1", 10)
    _answer(client, "u1", 60)
    assert state.values == {"u1": 60}


def test_clear_drops_answers_and_leaves_activity(client, state, pstate):
    client.post("/api/cur/host/aishare/start")
    _answer(client, "u1", 50)
    client.post("/api/cur/host/aishare/clear")
    assert state.values == {} and not state.active
    assert pstate.current_activity == "none"


def test_restart_drops_previous_round(client, state):
    client.post("/api/cur/host/aishare/start")
    _answer(client, "u1", 50)
    client.post("/api/cur/host/aishare/reveal", json={"revealed": True})
    client.post("/api/cur/host/aishare/start")
    assert state.values == {} and not state.revealed


def test_snapshot_round_trips():
    s = AiShareState()
    s.start()
    s.set_value("u1", 70)
    s.revealed = True
    restored = AiShareState()
    restored.restore(s.snapshot())
    assert restored.snapshot() == s.snapshot()
