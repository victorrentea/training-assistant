"""Feedback form persistence + shared state."""
import json

from daemon.misc.feedback_form import (
    FEEDBACK_FORM_FILE,
    load_feedback_form,
    save_feedback_form,
)
from daemon.session import state as session_shared_state


def test_save_then_load_roundtrip(tmp_path):
    created_at = save_feedback_form(tmp_path, "AI@Acme", "https://freeonlinesurveys.com/s/demo1234")
    loaded = load_feedback_form(tmp_path)
    assert loaded == {
        "title": "AI@Acme",
        "url": "https://freeonlinesurveys.com/s/demo1234",
        "created_at": created_at,
    }


def test_save_writes_readable_json_at_known_filename(tmp_path):
    save_feedback_form(tmp_path, "DDD@ING", "https://freeonlinesurveys.com/s/abc123")
    on_disk = json.loads((tmp_path / FEEDBACK_FORM_FILE).read_text(encoding="utf-8"))
    assert on_disk["url"] == "https://freeonlinesurveys.com/s/abc123"


def test_load_returns_none_when_absent(tmp_path):
    assert load_feedback_form(tmp_path) is None


def test_load_returns_none_on_corrupt_file(tmp_path):
    (tmp_path / FEEDBACK_FORM_FILE).write_text("{not json", encoding="utf-8")
    assert load_feedback_form(tmp_path) is None


def test_save_overwrites_previous_form(tmp_path):
    save_feedback_form(tmp_path, "Old", "https://freeonlinesurveys.com/s/old")
    save_feedback_form(tmp_path, "New", "https://freeonlinesurveys.com/s/new")
    assert load_feedback_form(tmp_path)["title"] == "New"


def test_shared_state_roundtrip():
    try:
        assert session_shared_state.get_feedback_url() is None
        session_shared_state.set_feedback_url("https://freeonlinesurveys.com/s/demo1234")
        assert session_shared_state.get_feedback_url() == "https://freeonlinesurveys.com/s/demo1234"
        session_shared_state.set_feedback_url(None)
        assert session_shared_state.get_feedback_url() is None
    finally:
        session_shared_state.set_feedback_url(None)
