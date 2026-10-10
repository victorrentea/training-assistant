"""The wiki note the host has open, relayed so participants can follow it."""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.misc import router as misc_router
from daemon.misc.state import misc_state
from daemon.ws_messages import WikiNoteMsg


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(misc_router.local_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_note():
    misc_state.wiki_note = None
    yield
    misc_state.wiki_note = None


def test_host_opening_a_note_is_broadcast_to_participants():
    with patch.object(misc_router, "broadcast") as broadcast:
        resp = _client().post("/wiki/note", json={"slug": "Concepts/Clean-Code"})

    assert resp.status_code == 200
    msg = broadcast.call_args.args[0]
    assert isinstance(msg, WikiNoteMsg)
    assert msg.model_dump() == {"type": "wiki_note", "slug": "Concepts/Clean-Code"}


def test_host_closing_the_note_is_broadcast_as_null():
    misc_state.wiki_note = "Home"
    with patch.object(misc_router, "broadcast") as broadcast:
        resp = _client().post("/wiki/note", json={"slug": None})

    assert resp.status_code == 200
    assert broadcast.call_args.args[0].model_dump() == {"type": "wiki_note", "slug": None}
    assert misc_state.wiki_note is None


def test_latest_note_is_kept_for_participants_who_join_later():
    with patch.object(misc_router, "broadcast"):
        _client().post("/wiki/note", json={"slug": "Home"})
        _client().post("/wiki/note", json={"slug": "Ședință/Notă"})

    assert misc_state.wiki_note == "Ședință/Notă"


def test_new_session_forgets_the_old_note():
    misc_state.wiki_note = "Home"
    misc_state.reset_for_new_session()
    assert misc_state.wiki_note is None


@pytest.mark.parametrize("slug", ["Home", "/", "Concepts/Clean-Code", "a.b", "Ședință ă"])
def test_note_slugs_the_wiki_produces_are_accepted(slug):
    with patch.object(misc_router, "broadcast"):
        resp = _client().post("/wiki/note", json={"slug": slug})

    assert resp.status_code == 200
    assert misc_state.wiki_note == slug


# A follower fetches the note at this path relative to its own wiki page: nothing
# that could make that fetch leave the wiki site reaches every screen.
@pytest.mark.parametrize("slug", [
    "",
    "//evil.example/x",
    "https://evil.example/x",
    "javascript:alert(1)",
    "a/../../api/x",
    "a\\b",
    "a?b",
    "a#b",
    "a\nb",
    "x" * 301,
])
def test_a_slug_that_could_leave_the_site_is_rejected(slug):
    with patch.object(misc_router, "broadcast") as broadcast:
        resp = _client().post("/wiki/note", json={"slug": slug})

    assert resp.status_code == 422
    broadcast.assert_not_called()
    assert misc_state.wiki_note is None
