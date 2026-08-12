"""Feedback form persistence + shared state."""
import json
from pathlib import Path

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


def test_post_feedback_form_400_on_blank_url(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from daemon.misc import router as misc_router

    sent = []
    monkeypatch.setattr(misc_router, "broadcast", lambda msg: sent.append(msg))
    monkeypatch.setattr(misc_router, "get_active_session_folder", lambda: tmp_path)

    app = FastAPI()
    app.include_router(misc_router.local_router)
    resp = TestClient(app).post("/feedback-form", json={"title": "AI@Acme", "url": "   "})

    assert resp.status_code == 400
    # a rejected request must leave no trace anywhere
    assert load_feedback_form(tmp_path) is None
    assert session_shared_state.get_feedback_url() is None
    assert sent == []


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
        assert client.get("/api/participant/state", headers=headers).json()["feedback_url"] is None

        session_shared_state.set_feedback_url("https://freeonlinesurveys.com/s/demo1234")
        served = client.get("/api/participant/state", headers=headers).json()
        assert served["feedback_url"] == "https://freeonlinesurveys.com/s/demo1234"
    finally:
        session_shared_state.set_feedback_url(None)


def test_boot_restore_reads_url_from_session_folder(tmp_path):
    """The daemon restarts on every push to master — the link must come back."""
    save_feedback_form(tmp_path, "AI@Acme", "https://freeonlinesurveys.com/s/demo1234")
    session_shared_state.set_feedback_url(None)  # simulate a fresh process
    try:
        restored = load_feedback_form(tmp_path)
        session_shared_state.set_feedback_url(restored["url"] if restored else None)
        assert session_shared_state.get_feedback_url() == "https://freeonlinesurveys.com/s/demo1234"
    finally:
        session_shared_state.set_feedback_url(None)


def test_session_switch_does_not_leak_the_previous_sessions_form(tmp_path):
    """Entering a session with no form must clear the previous session's URL.

    Otherwise one client's feedback form stays live in the next client's room.
    """
    previous = tmp_path / "2026-08-11..13 AI@Acme"
    previous.mkdir()
    save_feedback_form(previous, "AI@Acme", "https://freeonlinesurveys.com/s/old")
    session_shared_state.set_feedback_url("https://freeonlinesurveys.com/s/old")

    entering = tmp_path / "2026-08-20 DDD@ING"
    entering.mkdir()
    try:
        found = load_feedback_form(entering)
        session_shared_state.set_feedback_url(found["url"] if found else None)
        assert session_shared_state.get_feedback_url() is None
    finally:
        session_shared_state.set_feedback_url(None)


def test_session_switch_restores_a_resumed_sessions_form(tmp_path):
    """Re-entering a session whose form was already published restores it."""
    folder = tmp_path / "2026-08-11..13 AI@Acme"
    folder.mkdir()
    save_feedback_form(folder, "AI@Acme", "https://freeonlinesurveys.com/s/demo1234")
    session_shared_state.set_feedback_url(None)
    try:
        found = load_feedback_form(folder)
        session_shared_state.set_feedback_url(found["url"] if found else None)
        assert session_shared_state.get_feedback_url() == "https://freeonlinesurveys.com/s/demo1234"
    finally:
        session_shared_state.set_feedback_url(None)


def test_every_gdrive_url_call_site_has_a_feedback_url_counterpart():
    """The two session URLs must be published and cleared at the same places.

    The three tests above exercise the restore/clear logic but not its wiring:
    it lives inside the daemon's single long-running main loop in
    daemon/__main__.py, which cannot be imported piecemeal. Guard the wiring
    structurally instead — gdrive_url is set at boot (found/not found), on
    session switch and on teardown, and feedback_url must be set at every one
    of those points, or the previous client's form stays live in the next
    client's room.
    """
    source = (Path(__file__).resolve().parents[2] / "daemon" / "__main__.py").read_text(
        encoding="utf-8"
    )
    assert source.count("session_shared_state.set_feedback_url(") == source.count(
        "session_shared_state.set_gdrive_url("
    )
