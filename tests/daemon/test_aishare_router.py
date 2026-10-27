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


def _answer(client, pid, value, question="ai_generated", other=None, hearts=None):
    body = {"question": question, "value": value}
    if other is not None:
        body["other"] = other
    if hearts is not None:
        body["hearts"] = hearts
    return client.post("/api/participant/aishare/value", json=body, headers={"X-Participant-ID": pid})


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
    assert [q.id for q in pax.questions] == ["harness_work", "personal_sub", "agents_md", "knowledge_base", "mcp", "skill", "plugins", "custom_agent", "code_review", "nontech_pr", "ai_generated", "review", "devex_pain"]
    assert pax.questions[0].kind == "multi" and pax.questions[0].options[-1] == "Other"
    assert pax.questions[2].options == ["Yes", "No / I don't know"]
    assert [l.text for l in pax.questions[1].links] == ["Claude", "Codex"]
    assert pax.questions[3].options == ["Yes", "No / I don't know"]
    assert next(q for q in pax.questions if q.id == "skill").options == ["Yes", "No"]
    assert [q.kind for q in pax.questions[-3:]] == ["slider", "slider", "ranking"]


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


def test_other_harness_text_reaches_the_host_only(client, state, sent):
    client.post("/api/cur/host/aishare/start")
    _answer(client, "u1", 16, question="harness_work", other="  Cursor ")
    _answer(client, "u2", 16, question="harness_work", other="windsurf")
    client.post("/api/cur/host/aishare/reveal", json={"revealed": True})
    host = _last(sent["host"], "aishare_host_update")
    assert _result(host, "harness_work").others == ["Cursor", "windsurf"]
    pax = _last(sent["broadcast"], "aishare_updated")
    assert _result(pax, "harness_work").others is None
    assert "Cursor" not in pax.model_dump_json()
    assert state.others_of("u1") == {"harness_work": "Cursor"}


def test_other_text_dropped_when_another_option_is_picked(client, state):
    client.post("/api/cur/host/aishare/start")
    _answer(client, "u1", 16, question="harness_work", other="Cursor")
    _answer(client, "u1", 16, question="harness_work")          # re-clicking Other keeps the text
    assert state.others_of("u1") == {"harness_work": "Cursor"}
    _answer(client, "u1", 1, question="harness_work")       # Other unticked
    assert state.others_of("u1") == {}


def test_multi_counts_every_ticked_option_and_the_hearts(client, state, sent):
    client.post("/api/cur/host/aishare/start")
    _answer(client, "u1", 0b00011, question="harness_work", hearts=0b00011)   # two favourites
    _answer(client, "u2", 0b00101, question="harness_work", hearts=0b00001)
    host = _last(sent["host"], "aishare_host_update")
    assert _result(host, "harness_work").counts == [2, 1, 1, 0, 0]
    assert _result(host, "harness_work").hearts == [2, 1, 0, 0, 0]
    pax = _last(sent["broadcast"], "aishare_updated")
    assert _result(pax, "harness_work").hearts is None              # hidden until revealed
    client.post("/api/cur/host/aishare/reveal", json={"revealed": True})
    assert _result(_last(sent["broadcast"], "aishare_updated"), "harness_work").hearts == [2, 1, 0, 0, 0]


def test_multi_hearts_only_on_ticked_options_and_untick_all_withdraws(client, state):
    client.post("/api/cur/host/aishare/start")
    _answer(client, "u1", 0b00011, question="harness_work", hearts=0b00011)
    _answer(client, "u1", 0b00001, question="harness_work", hearts=0b00011)   # unticked a ❤️ one
    assert state.hearts_of("u1") == {"harness_work": 0b00001}
    _answer(client, "u1", 0b00001, question="harness_work", hearts=0b00010)   # ❤️ on an unticked one
    assert state.hearts_of("u1") == {}
    assert _answer(client, "u1", 0b100000, question="harness_work").status_code == 422
    _answer(client, "u1", 0, question="harness_work")
    assert state.answers_of("u1") == {}


def test_multi_snapshot_round_trips_the_hearts():
    s = AiShareState()
    s.start()
    s.set_value("u1", "harness_work", 0b10001, other="Cursor", hearts=0b10001)
    restored = AiShareState()
    restored.restore(s.snapshot())
    assert restored.snapshot() == s.snapshot()
    assert restored.hearts_of("u1") == {"harness_work": 0b10001}


def test_restore_turns_a_legacy_single_favourite_into_a_heart():
    s = AiShareState()
    s.restore({"active": True, "answers": {"harness_work": {"u1": 0b10001, "u2": 0b00001}},
               "favorites": {"harness_work": {"u1": 4, "u2": 3}}})   # u2's ❤️ was not ticked
    assert s.hearts == {"harness_work": {"u1": 0b10000}}


# ── Ranking: "What burns your ⏱️ time, 🧠 brain and 😡 emotions?" ──

def _vote(client, pid, item, vote):
    return client.post("/api/participant/aishare/vote", json={"question": "devex_pain", "item": item, "vote": vote},
                       headers={"X-Participant-ID": pid})


def _add(client, pid, text):
    return client.post("/api/participant/aishare/item", json={"question": "devex_pain", "text": text},
                       headers={"X-Participant-ID": pid})


def _ranking(msg):
    return [(i.text, i.score) for i in _result(msg, "devex_pain").items]


def test_ranking_starts_from_the_presets_with_no_votes(client, sent):
    client.post("/api/cur/host/aishare/start")
    items = _result(_last(sent["broadcast"], "aishare_updated"), "devex_pain").items
    assert items[0].text == "Code Review: waiting / performing" and len(items) == 10
    assert all(i.score is None for i in items)       # participants: no tallies before the reveal


def test_ranking_tallies_reach_participants_only_once_revealed(client, sent):
    client.post("/api/cur/host/aishare/start")
    assert _vote(client, "u1", 3, 1).status_code == 204       # Tech debt 🔥
    _vote(client, "u2", 3, 1)
    _vote(client, "u2", 2, 1)                                 # Bureaucracy 🔥
    ranking = [("Tech debt: legacy code, lack of tests", 2), ("Bureaucracy", 1),
               ("Code Review: waiting / performing", 0)]
    assert _ranking(_last(sent["host"], "aishare_host_update"))[:3] == ranking   # the host sees it live
    pax = _last(sent["broadcast"], "aishare_updated")
    assert _result(pax, "devex_pain").count == 2               # how many voted, but not for what
    items = _result(pax, "devex_pain").items
    assert all(i.score is None for i in items)
    assert [i.id for i in items] == sorted(i.id for i in items)  # the order they were added, not the votes'
    client.post("/api/cur/host/aishare/reveal", json={"revealed": True})
    assert _ranking(_last(sent["broadcast"], "aishare_updated"))[:3] == ranking


def test_items_added_by_participants_are_marked_custom(client, sent):
    client.post("/api/cur/host/aishare/start")
    client.post("/api/participant/aishare/item", json={"question": "devex_pain", "text": "No coffee"},
                headers={"X-Participant-ID": "u1"})
    items = _result(_last(sent["broadcast"], "aishare_updated"), "devex_pain").items
    assert [i.text for i in items if i.custom] == ["No coffee"]


def test_vote_zero_takes_it_back(client, state):
    client.post("/api/cur/host/aishare/start")
    _vote(client, "u1", 3, 1)
    assert state.votes_of("u1") == {"devex_pain": {"3": 1}}
    _vote(client, "u1", 3, 0)
    assert state.votes_of("u1") == {}


def test_vote_rejected_before_start_or_on_unknown_item(client):
    assert _vote(client, "u1", 0, 1).status_code == 409
    client.post("/api/cur/host/aishare/start")
    assert _vote(client, "u1", 99, 1).status_code == 409
    assert _vote(client, "u1", 0, 2).status_code == 422
    assert _vote(client, "u1", 0, -1).status_code == 422       # upvote only: no ▼


def test_ranking_cannot_be_answered_with_a_value(client):
    client.post("/api/cur/host/aishare/start")
    assert _answer(client, "u1", 1, question="devex_pain").status_code == 422


def test_added_item_gets_its_author_upvote_and_duplicates_fold(client, state, sent):
    client.post("/api/cur/host/aishare/start")
    resp = _add(client, "u1", "  Too many   Jira fields ")
    assert resp.status_code == 200
    new_id = resp.json()["id"]
    assert new_id == 10
    assert _add(client, "u2", "too many jira fields").json()["id"] == new_id
    assert _add(client, "u2", "CONTEXT SWITCHING").json()["id"] == 5      # same as a preset
    assert _ranking(_last(sent["host"], "aishare_host_update"))[:2] == [("Too many Jira fields", 2), ("Context switching", 1)]
    pax = _last(sent["broadcast"], "aishare_updated")
    assert "u1" not in pax.model_dump_json() and "u1" not in _last(sent["host"], "aishare_host_update").model_dump_json()


def test_a_participant_adds_at_most_five_items(client):
    client.post("/api/cur/host/aishare/start")
    for i in range(5):
        assert _add(client, "u1", f"pain {i}").status_code == 200
    assert _add(client, "u1", "pain 5").status_code == 409
    assert _add(client, "u2", "pain 5").status_code == 200


def test_host_deletes_an_item_with_its_votes(client, state, sent):
    client.post("/api/cur/host/aishare/start")
    item = _add(client, "u1", "something rude").json()["id"]
    _vote(client, "u2", item, 1)
    assert client.delete(f"/api/cur/host/aishare/items/devex_pain/{item}").status_code == 204
    assert "something rude" not in _last(sent["broadcast"], "aishare_updated").model_dump_json()
    assert state.votes == {"devex_pain": {}}
    assert client.delete(f"/api/cur/host/aishare/items/devex_pain/{item}").status_code == 404


def test_ranking_snapshot_round_trips():
    s = AiShareState()
    s.start()
    s.add_item("u1", "devex_pain", "Too many Jira fields")
    s.vote("u2", "devex_pain", 0, 1)
    s.delete_item("devex_pain", 5)
    restored = AiShareState()
    restored.restore(s.snapshot())
    assert restored.snapshot() == s.snapshot()
    assert restored.votes_of("u1") == {"devex_pain": {"10": 1}}


def test_restore_drops_downvotes_from_before_upvote_only():
    s = AiShareState()
    s.start()
    snap = s.snapshot()
    snap["votes"] = {"devex_pain": {"u1": {"0": 1, "1": -1}, "u2": {"2": -1}}}
    s.restore(snap)
    assert s.votes == {"devex_pain": {"u1": {0: 1}}}


def test_restore_merges_no_and_i_dont_know_on_agents_md():
    s = AiShareState()
    s.restore({"active": True, "answers": {"agents_md": {"u1": 0, "u2": 1, "u3": 2}}})
    assert s.answers == {"agents_md": {"u1": 0, "u2": 1, "u3": 1}}


def test_restore_renames_reworded_presets_but_keeps_their_votes():
    s = AiShareState()
    s.restore({"active": True,
               "items": {"devex_pain": [{"id": 0, "text": "Other teams: waiting on them", "by": None},
                                        {"id": 1, "text": "Other teams: waiting on them", "by": "u9"}]},
               "votes": {"devex_pain": {"u1": {"0": 1}}}})
    assert [it["text"] for it in s.items["devex_pain"]] == ["Blocked: by other teams", "Other teams: waiting on them"]
    assert s.votes == {"devex_pain": {"u1": {0: 1}}}


def test_restore_of_an_older_active_snapshot_seeds_the_ranking():
    s = AiShareState()
    s.restore({"active": True, "answers": {"ai_generated": {"u1": 40}}})
    assert len(s.ranked("devex_pain")) == 10
