"""Tests for the host `attendees.md` endpoint (host-attendees-pdf, phase 2).

The endpoint renders the attendance sheet fresh from the live roster on every
read, so it stays current as names change and degrades gracefully (200 + the
"no attendees yet" placeholder) when no session is active.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from daemon.attendees_router import router
from daemon.participant.state import participant_state
from daemon.scores import scores


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def active_folder(tmp_path, monkeypatch):
    """Point get_active_session_folder() at a real temp session folder.

    build_attendees_md() re-imports the symbol at call time, so patching the
    attribute on its home module is sufficient.
    """
    folder = tmp_path / "2026-07-24 AcmeCorp Clean Architecture"
    folder.mkdir()
    monkeypatch.setattr(
        "daemon.misc.content_files.get_active_session_folder", lambda: folder
    )
    return folder


@pytest.fixture(autouse=True)
def clean_state():
    participant_state.reset(mode="workshop")
    scores.scores.clear()
    yield
    participant_state.reset(mode="workshop")
    scores.scores.clear()


def test_returns_current_attendees_md(client, active_folder):
    participant_state.participant_names.update(
        {"u1": "Ada Lovelace", "u2": "Grace Hopper"}
    )
    r = client.get("/api/test-session/host/attendees.md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    body = r.text
    assert "# Attendance — 2026-07-24 AcmeCorp Clean Architecture" in body
    assert "Ada Lovelace" in body
    assert "Grace Hopper" in body
    assert "**2** attendee" in body


def test_updates_as_names_change(client, active_folder):
    # Empty roster first.
    r1 = client.get("/api/test-session/host/attendees.md")
    assert r1.status_code == 200
    assert "No attendees yet" in r1.text

    # A name appears.
    participant_state.participant_names["u1"] = "Ada Lovelace"
    r2 = client.get("/api/test-session/host/attendees.md")
    assert "Ada Lovelace" in r2.text

    # A rename is reflected on the next read, with the old name gone.
    participant_state.participant_names["u1"] = "Ada King"
    r3 = client.get("/api/test-session/host/attendees.md")
    assert "Ada King" in r3.text
    assert "Ada Lovelace" not in r3.text

    # A leave (name removed) drops back to the placeholder.
    participant_state.participant_names.clear()
    r4 = client.get("/api/test-session/host/attendees.md")
    assert "No attendees yet" in r4.text


def test_no_active_session_is_graceful(client, monkeypatch):
    monkeypatch.setattr(
        "daemon.misc.content_files.get_active_session_folder", lambda: None
    )
    # Even with names in memory, no active session → no server error, and the
    # response indicates no attendees document is available.
    participant_state.participant_names["u1"] = "Ada Lovelace"
    r = client.get("/api/test-session/host/attendees.md")
    assert r.status_code == 200
    assert "No attendees yet" in r.text


def test_anonymous_entries_are_distinguishable(client, active_folder):
    participant_state.participant_names.update({"u1": "Ada", "u2": "Gandalf"})
    # Explicit anonymity signal: u2 joined anonymously.
    participant_state.anonymous_pids.add("u2")
    r = client.get("/api/test-session/host/attendees.md")
    body = r.text
    assert "_Gandalf_ (anonymous)" in body
    ada_line = next(ln for ln in body.splitlines() if "Ada" in ln)
    assert "(anonymous)" not in ada_line


def test_endpoint_wired_into_host_app():
    """Smoke: the router is actually mounted in the real host app under the
    /api/{session_id}/host/attendees.md path (not just tested in isolation)."""
    from daemon.host_server import create_app

    app = create_app("https://interact.victorrentea.ro")
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/{session_id}/host/attendees.md" in paths


def test_marked_cdn_is_on_the_host_csp_whitelist():
    """The printable-PDF render depends on marked from cdn.jsdelivr.net; that host
    must remain on the host CSP script-src whitelist or the render breaks."""
    import re
    from pathlib import Path

    from daemon.host_server import _HOST_CSP

    host_html = Path(__file__).resolve().parents[2] / "static" / "host.html"
    text = host_html.read_text(encoding="utf-8")
    m = re.search(r'<script src="(https://[^"]*marked[^"]*)"', text)
    assert m, "marked script tag not found in host.html"
    assert "cdn.jsdelivr.net" in m.group(1)
    # jsdelivr must be whitelisted on script-src.
    script_src = next(
        d for d in _HOST_CSP.split(";") if d.strip().startswith("script-src")
    )
    assert "https://cdn.jsdelivr.net" in script_src
