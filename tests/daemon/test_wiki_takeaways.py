"""The wiki notes the trainer stars as key takeaways: broadcast live, kept on disk."""
import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.misc import router as misc_router
from daemon.participant import router as participant_router
from daemon.wiki import takeaways
from daemon.ws_messages import WikiTakeawaysMsg


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(misc_router.local_router)
    app.include_router(participant_router.router)
    return TestClient(app)


@pytest.fixture
def session_folder(tmp_path):
    takeaways.forget_cache()
    with patch.object(takeaways, "get_active_session_folder", return_value=tmp_path):
        yield tmp_path
    takeaways.forget_cache()


def _star(slug: str, starred: bool = True):
    return _client().post("/wiki/takeaway", json={"slug": slug, "starred": starred})


def test_starring_a_note_is_broadcast_to_participants_as_the_whole_set(session_folder):
    with patch.object(misc_router, "broadcast") as broadcast:
        _star("Self-review")
        resp = _star("Concepts/Clean-Code")

    assert resp.status_code == 200
    assert resp.json() == {"slugs": ["Concepts/Clean-Code", "Self-review"]}
    msg = broadcast.call_args.args[0]
    assert isinstance(msg, WikiTakeawaysMsg)
    assert msg.model_dump() == {"type": "wiki_takeaways", "slugs": ["Concepts/Clean-Code", "Self-review"]}


def test_unstarring_removes_the_note(session_folder):
    with patch.object(misc_router, "broadcast") as broadcast:
        _star("Self-review")
        resp = _star("Self-review", starred=False)

    assert resp.json() == {"slugs": []}
    assert broadcast.call_args.args[0].slugs == []


def test_stars_are_saved_in_the_session_folder_and_survive_a_restart(session_folder):
    with patch.object(misc_router, "broadcast"):
        _star("Self-review")

    saved = json.loads((session_folder / takeaways.TAKEAWAYS_FILE).read_text())
    assert saved == {"slugs": ["Self-review"]}
    takeaways.forget_cache()  # a daemon restart: nothing in memory
    assert _client().get("/api/participant/wiki/takeaways").json() == {"slugs": ["Self-review"]}


def test_a_session_switch_reads_the_entered_sessions_stars(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (b / takeaways.TAKEAWAYS_FILE).write_text(json.dumps({"slugs": ["Autonomy"]}))
    takeaways.forget_cache()
    with patch.object(takeaways, "get_active_session_folder", return_value=a), patch.object(misc_router, "broadcast"):
        _star("Self-review")
        assert takeaways.current_takeaways() == ["Self-review"]
    with patch.object(takeaways, "get_active_session_folder", return_value=b):
        assert takeaways.current_takeaways() == ["Autonomy"]
    takeaways.forget_cache()


def test_an_unreadable_file_means_no_stars(session_folder):
    (session_folder / takeaways.TAKEAWAYS_FILE).write_text("{not json")
    assert takeaways.current_takeaways() == []


def test_no_active_session_is_a_404_and_nothing_is_broadcast():
    takeaways.forget_cache()
    with patch.object(takeaways, "get_active_session_folder", return_value=None), \
            patch.object(misc_router, "broadcast") as broadcast:
        resp = _star("Self-review")
    assert resp.status_code == 404
    broadcast.assert_not_called()


@pytest.mark.parametrize("slug", ["", "../secret", "//evil.example/x", "https://evil.example", "a?b"])
def test_a_slug_must_be_a_path_inside_the_wiki(session_folder, slug):
    with patch.object(misc_router, "broadcast") as broadcast:
        resp = _star(slug)
    assert resp.status_code == 422
    broadcast.assert_not_called()


def test_the_participant_state_carries_the_stars(session_folder):
    with patch.object(misc_router, "broadcast"):
        _star("Self-review")
    resp = _client().get("/api/participant/state", headers={"X-Participant-ID": "p1"})
    assert resp.status_code == 200
    assert resp.json()["wiki_takeaways"] == ["Self-review"]
