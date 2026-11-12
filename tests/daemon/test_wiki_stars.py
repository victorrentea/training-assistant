"""Participants star the wiki notes they found interesting: counts for everyone, no forging."""
import io
import json
import zipfile
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.participant import router as participant_router
from daemon.participant.state import participant_state
from daemon.wiki import publisher, stars
from daemon.ws_messages import WikiStarsMsg

ALICE = "11111111-1111-4111-8111-111111111111"
BOB = "22222222-2222-4222-8222-222222222222"
NOTES = frozenset({"Self-review", "Concepts/Clean-Code", "Concepts/", "/"})


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(participant_router.router)
    return TestClient(app)


@pytest.fixture
def session(tmp_path):
    stars.forget_cache()
    participant_router._wiki_stars_fanout.reset()
    with patch.object(stars, "get_active_session_folder", return_value=tmp_path), \
            patch.object(participant_router, "published_notes", return_value=NOTES), \
            patch.dict(participant_state.participant_names, {ALICE: "Alice", BOB: "Bob"}), \
            patch.object(participant_router, "broadcast") as broadcast:
        # Most tests here are about the stars once the trainer revealed them; the
        # private round has its own tests below (`hidden`).
        stars.set_revealed(True)
        yield tmp_path, broadcast
    stars.forget_cache()
    participant_router._wiki_stars_fanout.reset()


def _star(pid: str | None, slug: str, starred: bool = True):
    headers = {"X-Participant-ID": pid} if pid else {}
    return _client().post("/api/participant/wiki/star", json={"slug": slug, "starred": starred}, headers=headers)


def test_a_star_is_counted_for_everyone_and_broadcast_without_who(session):
    _, broadcast = session
    _star(ALICE, "Self-review")
    resp = _star(BOB, "Self-review")

    assert resp.status_code == 200
    assert resp.json() == {"counts": {"Self-review": 2}, "starrers": 2, "revealed": True,
                           "mine": ["Self-review"], "done": False}
    msg = broadcast.call_args_list[0].args[0]
    assert isinstance(msg, WikiStarsMsg)
    assert msg.model_dump() == {"type": "wiki_stars", "counts": {"Self-review": 1}, "starrers": 1, "revealed": True}
    assert ALICE not in json.dumps(msg.model_dump())


def test_starring_twice_still_counts_one(session):
    _star(ALICE, "Self-review")
    resp = _star(ALICE, "Self-review")
    assert resp.json()["counts"] == {"Self-review": 1}


def test_unstarring_withdraws_only_your_own_star(session):
    _star(ALICE, "Self-review")
    _star(BOB, "Self-review")
    resp = _star(BOB, "Self-review", starred=False)
    assert resp.json() == {"counts": {"Self-review": 1}, "starrers": 1, "revealed": True, "mine": [], "done": False}


def test_an_unknown_participant_cannot_star(session):
    _, broadcast = session
    resp = _star("33333333-3333-4333-8333-333333333333", "Self-review")
    assert resp.status_code == 403
    assert _star(None, "Self-review").status_code == 400
    assert stars.star_counts() == {}
    broadcast.assert_not_called()


def test_only_a_note_of_the_published_wiki_can_be_starred(session):
    assert _star(ALICE, "Made-up-note").status_code == 404
    with patch.object(participant_router, "published_notes", return_value=None):
        assert _star(ALICE, "Self-review").status_code == 404
    assert stars.star_counts() == {}


def test_a_refused_star_leaves_a_trace_in_the_log(session):
    # On the participant's screen it only flips back: the log is the one place it shows.
    with patch("daemon.log.error") as error:
        _star(ALICE, "Made-up-note")
    error.assert_called_once_with("wiki", "Alice: ★ Made-up-note refused (404: No such note in the published wiki)")


@pytest.mark.parametrize("slug", ["", "../secret", "//evil.example/x", "https://evil.example", "a?b"])
def test_a_slug_must_be_a_path_inside_the_wiki(session, slug):
    assert _star(ALICE, slug).status_code == 422


def test_flooding_is_cut_off_by_the_rate_limit(session):
    for i in range(stars.RATE_LIMIT):
        assert _star(ALICE, "Self-review", starred=i % 2 == 0).status_code == 200
    assert _star(ALICE, "Self-review").status_code == 429
    assert _star(BOB, "Self-review").status_code == 200  # someone else is not slowed down


def test_stars_are_saved_in_the_session_folder_and_survive_a_restart(session):
    folder, _ = session
    _star(ALICE, "Self-review")
    saved = json.loads((folder / stars.STARS_FILE).read_text())
    assert saved == {"stars": {"Self-review": [ALICE]}, "revealed": True, "done": []}
    stars.forget_cache()  # a daemon restart: nothing in memory
    resp = _client().get("/api/participant/wiki/stars", headers={"X-Participant-ID": ALICE})
    assert resp.json() == {"counts": {"Self-review": 1}, "starrers": 1, "revealed": True,
                           "mine": ["Self-review"], "done": False}


def test_the_counts_without_an_identity_carry_no_mine(session):
    _star(ALICE, "Self-review")
    resp = _client().get("/api/participant/wiki/stars")
    assert resp.json() == {"counts": {"Self-review": 1}, "starrers": 1, "revealed": True, "mine": [], "done": False}


def test_an_unreadable_file_means_no_stars(session):
    folder, _ = session
    (folder / stars.STARS_FILE).write_text("{not json")
    assert stars.star_counts() == {}


def test_the_participant_state_carries_the_counts_and_own_stars(session):
    _star(ALICE, "Self-review")
    _star(BOB, "Concepts/Clean-Code")
    resp = _client().get("/api/participant/state", headers={"X-Participant-ID": ALICE})
    body = resp.json()
    assert body["wiki_stars"] == {"Concepts/Clean-Code": 1, "Self-review": 1}
    assert body["wiki_my_stars"] == ["Self-review"]
    assert body["wiki_starrers"] == 2
    assert body["wiki_stars_revealed"] is True
    assert body["wiki_done"] is False


def test_the_starrers_are_the_participants_with_at_least_one_star(session):
    _star(ALICE, "Self-review")
    _star(ALICE, "Concepts/Clean-Code")
    _star(BOB, "Self-review")
    assert stars.starrer_count() == 2
    resp = _star(BOB, "Self-review", starred=False)
    assert resp.json()["starrers"] == 1


def test_deleting_a_participant_withdraws_their_stars(session):
    from daemon.participant.purge import purge_participant

    _star(ALICE, "Self-review")
    _star(BOB, "Self-review")
    report = purge_participant(ALICE)
    assert report.removed.get("wiki_star") == 1
    assert stars.star_counts() == {"Self-review": 1}


def test_published_notes_are_the_graph_node_ids_of_the_uploaded_site():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in ("index.html", "Self-review.html", "Concepts/index.html", "Concepts/Clean-Code.html",
                     "404.html", "static/contentIndex.json"):
            z.writestr(name, "x")
    fake = type("P", (), {"_payload": buf.getvalue()})()
    with patch.object(publisher, "_installed", fake):
        assert publisher.published_notes() == NOTES


# ── The private round: each sees only their own stars until the trainer reveals them ──

@pytest.fixture
def hidden(session):
    stars.set_revealed(False)
    return session


def _done(pid: str, done: bool = True):
    return _client().post("/api/participant/wiki/done", json={"done": done}, headers={"X-Participant-ID": pid})


def _trainer_client() -> TestClient:
    from daemon.misc import router as misc_router

    app = FastAPI()
    app.include_router(misc_router.local_router)
    return TestClient(app)


def test_a_new_session_starts_with_the_stars_private(tmp_path):
    stars.forget_cache()
    with patch.object(stars, "get_active_session_folder", return_value=tmp_path):
        assert stars.revealed() is False
    stars.forget_cache()


def test_while_hidden_a_participant_sees_only_their_own_stars(hidden):
    _, broadcast = hidden
    _star(ALICE, "Self-review")
    resp = _star(BOB, "Self-review")
    _star(BOB, "Concepts/Clean-Code")

    assert resp.json()["counts"] == {"Self-review": 1}
    alice = _client().get("/api/participant/state", headers={"X-Participant-ID": ALICE}).json()
    assert alice["wiki_stars"] == {"Self-review": 1}
    assert alice["wiki_stars_revealed"] is False
    assert _client().get("/api/participant/wiki/stars").json()["counts"] == {}
    # The broadcast reaches everyone: no counts at all while hidden, only the head count.
    for call in broadcast.call_args_list:
        assert call.args[0].counts == {} and call.args[0].revealed is False


def test_the_trainer_sees_every_star_and_how_many_are_done_while_hidden(hidden):
    _star(ALICE, "Self-review")
    _star(BOB, "Self-review")
    assert _done(ALICE).json()["done"] is True

    body = _trainer_client().get("/wiki/stars").json()
    assert body == {"counts": {"Self-review": 2}, "starrers": 2, "revealed": False, "done_count": 1}


def test_done_can_be_taken_back(hidden):
    _done(ALICE)
    assert _done(ALICE, done=False).json()["done"] is False
    assert stars.done_count() == 0


def test_only_a_joined_participant_can_be_done(hidden):
    assert _done("33333333-3333-4333-8333-333333333333").status_code == 403
    assert _client().post("/api/participant/wiki/done", json={"done": True}).status_code == 400
    assert stars.done_count() == 0


def test_revealing_shows_everyones_stars_to_everyone(hidden):
    from daemon.misc import router as misc_router

    _star(ALICE, "Self-review")
    _star(BOB, "Self-review")
    _done(ALICE)
    with patch.object(misc_router, "broadcast") as broadcast:
        body = _trainer_client().post("/wiki/reveal", json={"revealed": True}).json()
    assert body == {"counts": {"Self-review": 2}, "starrers": 2, "revealed": True, "done_count": 1}
    assert broadcast.call_args.args[0].model_dump() == {
        "type": "wiki_stars", "counts": {"Self-review": 2}, "starrers": 2, "revealed": True}
    assert _client().get("/api/participant/wiki/stars", headers={"X-Participant-ID": ALICE}).json()["counts"] == {
        "Self-review": 2}


def test_hiding_them_again_starts_a_new_round(hidden):
    _done(ALICE)
    with patch("daemon.misc.router.broadcast"):
        _trainer_client().post("/wiki/reveal", json={"revealed": True})
        body = _trainer_client().post("/wiki/reveal", json={"revealed": False}).json()
    assert body["revealed"] is False
    assert body["done_count"] == 0


def test_reveal_and_done_survive_a_restart(hidden):
    folder, _ = hidden
    _done(ALICE)
    stars.forget_cache()
    assert stars.is_done(ALICE) is True
    assert stars.revealed() is False
    assert json.loads((folder / stars.STARS_FILE).read_text())["done"] == [ALICE]


def test_deleting_a_participant_forgets_they_were_done(hidden):
    from daemon.participant.purge import purge_participant

    _done(ALICE)
    purge_participant(ALICE)
    assert stars.done_count() == 0
