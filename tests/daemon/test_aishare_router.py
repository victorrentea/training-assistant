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


def _answer(client, pid, value, question="ai_generated"):
    return client.post("/api/participant/aishare/value", json={"question": question, "value": value},
                       headers={"X-Participant-ID": pid})


def _last(msgs, type_):
    return [m for m in msgs if m.type == type_][-1]


def _result(msg, qid):
    return next(r for r in msg.results if r.id == qid)


def test_start_routes_everyone_to_the_activity(client, pstate, sent):
    assert client.post("/api/cur/host/aishare/start").status_code == 204
    assert pstate.current_activity == "aishare"
    types = [m.type for m in sent["broadcast"]]
    assert types[:2] == ["activity_updated", "aishare_opened"]


def test_questions_are_shipped_in_order(client, sent):
    client.post("/api/cur/host/aishare/start")
    pax = _last(sent["broadcast"], "aishare_updated")
    assert [q.id for q in pax.questions] == ["harness", "agents_md", "mcp", "skill", "plugins", "custom_agent", "code_review", "ai_generated", "review"]
    assert pax.questions[0].options[-1] == "Other"
    assert pax.questions[1].options == ["Yes", "No", "I don't know"]
    assert [q.kind for q in pax.questions[-2:]] == ["slider", "slider"]


def test_answer_rejected_before_start(client):
    assert _answer(client, "u1", 40).status_code == 409


def test_answer_out_of_range_rejected(client):
    client.post("/api/cur/host/aishare/start")
    assert _answer(client, "u1", 101).status_code == 422
    assert _answer(client, "u1", -1).status_code == 422
    assert _answer(client, "u1", 3, question="mcp").status_code == 422
    assert _answer(client, "u1", 1, question="nope").status_code == 422


def test_answers_hidden_from_participants_until_revealed(client, sent):
    client.post("/api/cur/host/aishare/start")
    _answer(client, "u1", 80)
    _answer(client, "u2", 20)
    _answer(client, "u1", 0, question="mcp")
    _answer(client, "u2", 2, question="mcp")

    pax = _last(sent["broadcast"], "aishare_updated")
    assert _result(pax, "ai_generated").count == 2 and _result(pax, "ai_generated").values is None
    assert _result(pax, "mcp").count == 2 and _result(pax, "mcp").counts is None
    host = _last(sent["host"], "aishare_host_update")
    assert _result(host, "ai_generated").values == [20, 80]
    assert _result(host, "mcp").counts == [1, 0, 1]

    client.post("/api/cur/host/aishare/reveal", json={"revealed": True})
    pax = _last(sent["broadcast"], "aishare_updated")
    assert _result(pax, "ai_generated").values == [20, 80]
    assert _result(pax, "mcp").counts == [1, 0, 1]


def test_everything_is_anonymous(client, sent):
    client.post("/api/cur/host/aishare/start")
    _answer(client, "u1", 80)
    client.post("/api/cur/host/aishare/reveal", json={"revealed": True})
    for msg in (_last(sent["broadcast"], "aishare_updated"), _last(sent["host"], "aishare_host_update")):
        dumped = msg.model_dump_json()
        assert "Ana" not in dumped and "u1" not in dumped


def test_last_answer_wins(client, state):
    client.post("/api/cur/host/aishare/start")
    _answer(client, "u1", 10)
    _answer(client, "u1", 60)
    assert state.answers == {"ai_generated": {"u1": 60}}


def test_clear_drops_answers_and_leaves_activity(client, state, pstate):
    client.post("/api/cur/host/aishare/start")
    _answer(client, "u1", 50)
    client.post("/api/cur/host/aishare/clear")
    assert state.answers == {} and not state.active
    assert pstate.current_activity == "none"


def test_restart_drops_previous_round(client, state):
    client.post("/api/cur/host/aishare/start")
    _answer(client, "u1", 50)
    client.post("/api/cur/host/aishare/reveal", json={"revealed": True})
    client.post("/api/cur/host/aishare/start")
    assert state.answers == {} and not state.revealed


def test_snapshot_round_trips():
    s = AiShareState()
    s.start()
    s.set_value("u1", "ai_generated", 70)
    s.set_value("u1", "skill", 1)
    s.revealed = True
    restored = AiShareState()
    restored.restore(s.snapshot())
    assert restored.snapshot() == s.snapshot()
    assert restored.answers_of("u1") == {"ai_generated": 70, "skill": 1}


def test_restore_reads_the_legacy_single_slider_shape():
    s = AiShareState()
    s.restore({"active": True, "revealed": False, "values": {"u1": 40, "u2": 150}})
    assert s.answers == {"ai_generated": {"u1": 40}}
