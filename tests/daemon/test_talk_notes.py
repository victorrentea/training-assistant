"""The session notes the trainer has open in VS Code, mirrored onto talk phones."""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.misc import router as misc_router
from daemon.misc import talk_notes
from daemon.misc.state import misc_state
from daemon.participant.state import participant_state
from daemon.ws_messages import PresenterViewMsg, TalkNotesMsg


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(misc_router.local_router)
    return TestClient(app)


@pytest.fixture
def session(tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("+ one\n- two\n", encoding="utf-8")
    old_mode = participant_state.mode
    participant_state.mode = "talk"
    misc_state.talk_notes = None
    misc_state.presenter_view = "slides"
    with patch.object(talk_notes, "get_active_session_folder", return_value=tmp_path), \
         patch.object(talk_notes, "broadcast") as broadcast:
        yield notes, broadcast
    participant_state.mode = old_mode
    misc_state.talk_notes = None
    misc_state.presenter_view = "slides"


def _post(path, **body):
    return _client().post("/notes/live", json={"path": str(path), **body})


def test_another_file_is_ignored(session, tmp_path):
    _, broadcast = session
    other = tmp_path / "other.md"
    other.write_text("x", encoding="utf-8")

    resp = _post(other, text="secret", line=0, focused=True)

    assert resp.json() == {"tracked": False, "need_text": False}
    broadcast.assert_not_called()
    assert misc_state.talk_notes is None
    assert misc_state.presenter_view == "slides"


def test_first_report_carries_the_text_to_the_phones(session):
    notes, broadcast = session

    resp = _post(notes, text="+ one\n- two\n", line=1, collapsed=[0])

    assert resp.json() == {"tracked": True, "need_text": False}
    msg = broadcast.call_args.args[0]
    assert isinstance(msg, TalkNotesMsg)
    assert msg.model_dump() == {"type": "talk_notes", "revision": 1, "text": "+ one\n- two\n",
                                "line": 1, "selection": None, "collapsed": [0]}


def test_cursor_moves_travel_without_the_text(session):
    notes, broadcast = session
    _post(notes, text="+ one\n- two\n", line=0)

    _post(notes, line=1, selection={"start_line": 1, "start_char": 2, "end_line": 1, "end_char": 5})

    msg = broadcast.call_args.args[0]
    assert msg.text is None and msg.revision == 1 and msg.line == 1
    assert misc_state.talk_notes["text"] == "+ one\n- two\n"


def test_an_unchanged_report_is_not_rebroadcast(session):
    notes, broadcast = session
    _post(notes, text="+ one\n", line=0)
    broadcast.reset_mock()

    _post(notes, line=0)

    broadcast.assert_not_called()


def test_after_a_restart_the_daemon_asks_for_the_text(session):
    notes, broadcast = session

    resp = _post(notes, line=3)

    assert resp.json() == {"tracked": True, "need_text": True}
    broadcast.assert_not_called()


def test_focusing_the_notes_switches_the_phones_to_notes_once(session):
    notes, broadcast = session

    _post(notes, text="+ one\n", line=0, focused=True)
    _post(notes, line=0, focused=True)

    views = [c.args[0] for c in broadcast.call_args_list if isinstance(c.args[0], PresenterViewMsg)]
    assert [v.view for v in views] == ["notes"]
    assert misc_state.presenter_view == "notes"


def test_a_slide_switches_back_to_slides(session):
    _, broadcast = session
    misc_state.presenter_view = "notes"

    talk_notes.set_presenter_view("slides")

    assert broadcast.call_args.args[0].model_dump() == {"type": "presenter_view", "view": "slides"}


def test_workshop_mode_keeps_the_notes_off_the_wire(session):
    notes, broadcast = session
    participant_state.mode = "workshop"

    _post(notes, text="+ one\n", line=0, focused=True)

    broadcast.assert_not_called()


def test_new_session_forgets_the_notes():
    misc_state.talk_notes = {"revision": 1, "text": "x", "line": 0, "selection": None, "collapsed": []}
    misc_state.presenter_view = "notes"
    misc_state.reset_for_new_session()
    assert misc_state.talk_notes is None and misc_state.presenter_view == "slides"
