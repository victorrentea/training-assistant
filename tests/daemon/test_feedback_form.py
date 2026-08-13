"""Feedback form persistence + shared state."""
import json
from pathlib import Path

import pytest

from daemon.misc.feedback_form import (
    FEEDBACK_FORM_FILE,
    clear_feedback_form,
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


def test_clear_deletes_the_marker_so_a_restart_cannot_resurrect_the_link(tmp_path):
    """Deleting, not blanking: the boot restore keys off the file's existence."""
    save_feedback_form(tmp_path, "AI@Acme", "https://freeonlinesurveys.com/s/demo1234")
    assert clear_feedback_form(tmp_path) is True
    assert not (tmp_path / FEEDBACK_FORM_FILE).exists()
    assert load_feedback_form(tmp_path) is None


def test_clear_is_idempotent_when_nothing_was_published(tmp_path):
    """Retracting nothing is a no-op, not an error — the caller may retry blindly."""
    assert clear_feedback_form(tmp_path) is False


@pytest.mark.parametrize(
    "stored_url",
    [
        pytest.param(12345, id="int"),
        pytest.param(["https://freeonlinesurveys.com/s/x"], id="list"),
        pytest.param({"href": "https://freeonlinesurveys.com/s/x"}, id="dict"),
        pytest.param("not a url at all", id="free_text"),
        pytest.param("/s/demo1234", id="bare_path"),
        pytest.param("javascript:alert(1)", id="javascript_scheme"),
        pytest.param("file:///etc/passwd", id="file_scheme"),
        pytest.param("", id="empty"),
        pytest.param(None, id="null"),
    ],
)
def test_load_holds_the_file_to_the_endpoint_s_own_standard(tmp_path, stored_url):
    """The read-back path validates exactly what the POST path validates.

    ``/api/participant/state`` returns ``JSONResponse(dict)``, so whatever this
    function returns is served verbatim and assigned to ``nav.href``. A file
    hand-edited (or half-written) into holding an int, a list or ``javascript:``
    must not reach a participant screen through the back door, when the very same
    value posted to /feedback-form would have been rejected with a 422.
    """
    (tmp_path / FEEDBACK_FORM_FILE).write_text(
        json.dumps({"title": "AI@Acme", "url": stored_url, "created_at": ""}),
        encoding="utf-8",
    )
    assert load_feedback_form(tmp_path) is None


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


def test_delete_feedback_form_retracts_from_disk_state_and_participants(tmp_path, monkeypatch):
    """The undo for a wrong publish must reach all three places the publish did.

    A link published by mistake reaches every participant screen; leaving any one
    of disk / shared state / connected browsers un-cleared means it comes back —
    at the next daemon restart, for the next joiner, or not at all for the people
    already looking at it.
    """
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
        client.post(
            "/feedback-form",
            json={"title": "Oops", "url": "https://example.com/"},
        )
        sent.clear()

        resp = client.delete("/feedback-form")
        assert resp.status_code == 200, resp.text
        # names the link it destroyed: this endpoint targets "whatever is active",
        # so a retry after a session switch would take out a different room's form
        assert resp.json() == {"retracted": True, "url": "https://example.com/"}

        # the marker is gone, so a daemon restart cannot resurrect the link
        assert not (tmp_path / FEEDBACK_FORM_FILE).exists()
        # participants joining later get nothing
        assert session_shared_state.get_feedback_url() is None
        # participants already connected are told to hide it
        assert len(sent) == 1
        assert sent[0].type == "feedback_form_updated"
        assert sent[0].feedback_url is None
    finally:
        session_shared_state.set_feedback_url(None)


def test_delete_feedback_form_is_not_an_error_when_nothing_is_published(tmp_path, monkeypatch):
    """Idempotent: retracting nothing still succeeds, and still repairs browsers.

    The broadcast goes out regardless — a participant showing a link the daemon
    no longer knows about is exactly the state a blind retry is trying to fix.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from daemon.misc import router as misc_router

    sent = []
    monkeypatch.setattr(misc_router, "broadcast", lambda msg: sent.append(msg))
    monkeypatch.setattr(misc_router, "get_active_session_folder", lambda: tmp_path)

    app = FastAPI()
    app.include_router(misc_router.local_router)
    resp = TestClient(app).delete("/feedback-form")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"retracted": False, "url": None}  # nothing to undo, but no error
    assert session_shared_state.get_feedback_url() is None
    assert [msg.feedback_url for msg in sent] == [None]


def test_delete_feedback_form_repairs_the_room_even_when_the_disk_refuses(tmp_path, monkeypatch):
    """A failed unlink must not cost the repair that would have worked.

    Deleting can fail (EPERM, read-only volume, EISDIR). Taking the link off
    every screen cannot, so it happens first — and the surviving marker is then
    reported as a 500, because the next restart would otherwise resurrect the
    link with nobody having been told.
    """
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
        client.post("/feedback-form", json={"title": "Oops", "url": "https://example.com/"})
        sent.clear()

        def _refuse(_folder):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(misc_router, "clear_feedback_form", _refuse)
        resp = client.delete("/feedback-form")

        assert resp.status_code == 500, resp.text
        assert "feedback-form.json" in resp.json()["detail"]
        # …but the room is already clean
        assert session_shared_state.get_feedback_url() is None
        assert [msg.feedback_url for msg in sent] == [None]
    finally:
        session_shared_state.set_feedback_url(None)


def test_delete_feedback_form_404_without_active_session(monkeypatch):
    """Same shape as the publish endpoint: no session is a 404, not a silent no-op."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from daemon.misc import router as misc_router

    monkeypatch.setattr(misc_router, "get_active_session_folder", lambda: None)
    app = FastAPI()
    app.include_router(misc_router.local_router)
    resp = TestClient(app).delete("/feedback-form")
    assert resp.status_code == 404
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
    """A reconnecting participant is really served the URL, over the wire.

    Note what this does NOT prove: the handler returns ``JSONResponse(state_msg)``
    (daemon/participant/router.py), which bypasses ``response_model`` entirely —
    a value of the wrong type, or a field absent from ``ParticipantStateResponse``,
    is served verbatim rather than filtered or coerced. What this test earns is
    the other direction: that the dict entry exists and reaches the wire at all.
    The declared-contract side is guarded by its companion above,
    ``test_participant_state_payload_carries_feedback_url``.
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
    # block (widest real gap today: 14 lines), while the pairs themselves are
    # hundreds of lines apart.
    orphans = [
        line + 1  # 1-based, to match the editor
        for line in gdrive_sites
        if not any(abs(other - line) <= 20 for other in feedback_sites)
    ]
    assert not orphans, f"gdrive_url call sites with no feedback_url nearby: lines {orphans}"
