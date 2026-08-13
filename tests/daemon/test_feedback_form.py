"""Feedback form persistence + shared state."""
import json
from pathlib import Path

import pytest

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


def test_post_feedback_form_persists_broadcasts_and_publishes(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from daemon.misc import router as misc_router

    sent = []
    monkeypatch.setattr(misc_router, "broadcast", lambda msg: sent.append(msg))
    monkeypatch.setattr(misc_router, "get_active_session_folder", lambda: tmp_path)

    app = FastAPI()
    app.include_router(misc_router.local_router)
    client = TestClient(app)
    try:
        resp = client.post(
            "/feedback-form",
            json={"title": "AI@Acme", "url": "https://freeonlinesurveys.com/s/demo1234"},
        )
        assert resp.status_code == 200
        assert resp.json()["url"] == "https://freeonlinesurveys.com/s/demo1234"

        # persisted for restart survival
        assert load_feedback_form(tmp_path)["title"] == "AI@Acme"
        # published to participants joining later
        assert session_shared_state.get_feedback_url() == "https://freeonlinesurveys.com/s/demo1234"
        # pushed to participants already connected
        assert len(sent) == 1
        assert sent[0].type == "feedback_form_updated"
        assert sent[0].feedback_url == "https://freeonlinesurveys.com/s/demo1234"
    finally:
        session_shared_state.set_feedback_url(None)


def test_post_feedback_form_404_without_active_session(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from daemon.misc import router as misc_router

    monkeypatch.setattr(misc_router, "get_active_session_folder", lambda: None)
    app = FastAPI()
    app.include_router(misc_router.local_router)
    resp = TestClient(app).post(
        "/feedback-form",
        json={"title": "AI@Acme", "url": "https://freeonlinesurveys.com/s/demo1234"},
    )
    assert resp.status_code == 404
    # not merely an unregistered route — the handler ran and found no session
    assert resp.json()["detail"] == "no active session"


def test_post_feedback_form_logs_the_publish_to_stdout(tmp_path, monkeypatch, capsys):
    """The publish must be visible in the daemon log — it is the only trace of it.

    Guards against reaching for the stdlib `logger`, which prints nothing here:
    nothing in daemon/ configures stdlib logging, so an INFO record reaches only
    logging.lastResort (WARNING) and is dropped.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from daemon.misc import router as misc_router

    monkeypatch.setattr(misc_router, "broadcast", lambda msg: None)
    monkeypatch.setattr(misc_router, "get_active_session_folder", lambda: tmp_path)

    app = FastAPI()
    app.include_router(misc_router.local_router)
    try:
        TestClient(app).post(
            "/feedback-form",
            json={"title": "AI@Acme", "url": "https://freeonlinesurveys.com/s/demo1234"},
        )
    finally:
        session_shared_state.set_feedback_url(None)

    printed = capsys.readouterr().out
    # daemon/log.py pads/truncates the logger name to 7 chars: "feedback-form" -> "feedbac"
    assert "[feedbac] info " in printed
    assert "↑ Published: AI@Acme → https://freeonlinesurveys.com/s/demo1234" in printed


@pytest.mark.parametrize(
    "bad_url",
    [
        pytest.param("   ", id="blank"),
        pytest.param("not a url at all", id="free_text"),
        pytest.param("/s/demo1234", id="bare_path"),
        pytest.param("freeonlinesurveys.com/s/demo1234", id="no_scheme"),
    ],
)
def test_post_feedback_form_rejects_anything_that_is_not_a_url(tmp_path, monkeypatch, bad_url):
    """Garbage must never reach a participant screen — and must leave no trace.

    422, not 400: `url` is a Pydantic ``HttpUrl``, so FastAPI rejects the body
    before the handler runs. That is the point — the daemon, not just the calling
    skill, is what stands between arbitrary text and everyone's browser.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from daemon.misc import router as misc_router

    sent = []
    monkeypatch.setattr(misc_router, "broadcast", lambda msg: sent.append(msg))
    monkeypatch.setattr(misc_router, "get_active_session_folder", lambda: tmp_path)

    app = FastAPI()
    app.include_router(misc_router.local_router)
    resp = TestClient(app).post("/feedback-form", json={"title": "AI@Acme", "url": bad_url})

    assert resp.status_code == 422, resp.text
    # a rejected request must leave no trace anywhere
    assert load_feedback_form(tmp_path) is None
    assert session_shared_state.get_feedback_url() is None
    assert sent == []


def test_post_feedback_form_keeps_the_url_a_plain_string_everywhere(tmp_path, monkeypatch):
    """HttpUrl is a Url object, not a str — every hop must carry the string form.

    The participant page does ``nav.href = url``, so a serialised object anywhere
    in this chain breaks the link silently rather than loudly.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from daemon.misc import router as misc_router

    sent = []
    monkeypatch.setattr(misc_router, "broadcast", lambda msg: sent.append(msg))
    monkeypatch.setattr(misc_router, "get_active_session_folder", lambda: tmp_path)

    app = FastAPI()
    app.include_router(misc_router.local_router)
    url = "https://freeonlinesurveys.com/s/demo1234"
    try:
        resp = TestClient(app).post("/feedback-form", json={"title": "AI@Acme", "url": url})
        assert resp.status_code == 200, resp.text

        on_disk = json.loads((tmp_path / FEEDBACK_FORM_FILE).read_text(encoding="utf-8"))
        assert on_disk["url"] == url and isinstance(on_disk["url"], str)
        assert isinstance(sent[0].feedback_url, str) and sent[0].feedback_url == url
        assert isinstance(session_shared_state.get_feedback_url(), str)
        assert isinstance(resp.json()["url"], str) and resp.json()["url"] == url
    finally:
        session_shared_state.set_feedback_url(None)


def test_participant_state_payload_carries_feedback_url():
    """A participant loading or reconnecting mid-session must see the link."""
    from daemon.participant.router import ParticipantStateResponse

    assert "feedback_url" in ParticipantStateResponse.model_fields
    field = ParticipantStateResponse.model_fields["feedback_url"]
    assert field.default is None


def test_participant_state_endpoint_serves_the_published_url():
    """The link must survive the response_model filter, not just exist on it.

    A field added to the payload dict but not to ParticipantStateResponse (or
    vice versa) is silently dropped by FastAPI, so the served response is the
    only honest proof that a reconnecting participant sees the form.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from daemon.participant.router import router as participant_router

    app = FastAPI()
    app.include_router(participant_router)
    client = TestClient(app)
    headers = {"X-Participant-ID": "11111111-2222-3333-4444-555555555555"}
    try:
        session_shared_state.set_feedback_url(None)
        # status first: a 500 would otherwise surface as a confusing KeyError
        empty = client.get("/api/participant/state", headers=headers)
        assert empty.status_code == 200, empty.text
        assert empty.json()["feedback_url"] is None

        session_shared_state.set_feedback_url("https://freeonlinesurveys.com/s/demo1234")
        served = client.get("/api/participant/state", headers=headers)
        assert served.status_code == 200, served.text
        assert served.json()["feedback_url"] == "https://freeonlinesurveys.com/s/demo1234"
    finally:
        session_shared_state.set_feedback_url(None)


def test_every_gdrive_url_call_site_has_a_feedback_url_counterpart():
    """Structural guard: feedback_url is published wherever gdrive_url is.

    This asserts nothing about runtime behaviour — it reads daemon/__main__.py as
    text. The wiring it guards lives inside run(), a long-running main loop that
    cannot be imported piecemeal, so the only cheap check available is that the
    four gdrive_url publication points (boot found, boot not-found, session
    switch, teardown) each carry a feedback_url call beside them. Without the
    session-switch one, the previous client's form stays live in the next
    client's room; the arithmetic alone would not catch that, hence the
    proximity check.
    """
    source_lines = (
        (Path(__file__).resolve().parents[2] / "daemon" / "__main__.py")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    def line_numbers_calling(setter: str) -> list[int]:
        return [i for i, line in enumerate(source_lines) if f"session_shared_state.{setter}(" in line]

    gdrive_sites = line_numbers_calling("set_gdrive_url")
    feedback_sites = line_numbers_calling("set_feedback_url")

    # absolute, not just equal: 0 == 0 would mean both features were ripped out
    assert len(gdrive_sites) == 4, f"expected 4 gdrive_url call sites, found {len(gdrive_sites)}"
    assert len(feedback_sites) == len(gdrive_sites)

    # co-location: a feedback_url call in some unrelated branch satisfies the
    # arithmetic while the session-switch site silently regresses. The window is
    # 20 lines because each counterpart sits behind its own explanatory comment
    # block (widest real gap today: 14 lines), while the sites themselves are
    # hundreds of lines apart.
    orphans = [
        line + 1  # 1-based, to match the editor
        for line in gdrive_sites
        if not any(abs(other - line) <= 20 for other in feedback_sites)
    ]
    assert not orphans, f"gdrive_url call sites with no feedback_url nearby: lines {orphans}"
