"""Contract tests for participant HTML page routing (tabs + relocated notes page)."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from railway.app import app, state
from railway.features.pages.router import _PARTICIPANT_TAB_SLUGS

# A marker unique to the participant SPA (present in static/participant.html,
# absent from the standalone static/notes.html).
_APP_MARKER = b'data-nav="activity"'


def setup_function():
    state.reset()
    state.session_id = "e2etst"


def teardown_function():
    state.reset()


def test_root_serves_participant_app():
    client = TestClient(app)
    resp = client.get(f"/{state.session_id}/")
    assert resp.status_code == 200
    assert _APP_MARKER in resp.content


def test_tab_slug_serves_participant_app():
    client = TestClient(app)
    for tab in ("notes", "files", "slides", "activity", "summary",
                "agenda", "upload-paste", "feedback", "past-slides"):
        resp = client.get(f"/{state.session_id}/{tab}")
        assert resp.status_code == 200, tab
        assert _APP_MARKER in resp.content, tab


def test_notes_print_serves_readonly_page():
    client = TestClient(app)
    resp = client.get(f"/{state.session_id}/notes-print")
    assert resp.status_code == 200
    assert b"Session Notes" in resp.content
    assert _APP_MARKER not in resp.content  # not the SPA


def test_unknown_tab_is_404():
    client = TestClient(app)
    resp = client.get(f"/{state.session_id}/totally-bogus")
    assert resp.status_code == 404


def test_frontend_views_are_all_routable():
    """Every SPA tab (VIEWS in participant.html) must have a backend route slug,
    else its deep link would 404. Guards manual frontend/backend drift."""
    html = Path("static/participant.html").read_text(encoding="utf-8")
    m = re.search(r"var VIEWS\s*=\s*\[([^\]]*)\]", html)
    assert m, "could not find VIEWS array in static/participant.html"
    views = re.findall(r"'([^']+)'", m.group(1))
    assert views, "VIEWS array parsed empty"
    missing = [v for v in views if v not in _PARTICIPANT_TAB_SLUGS]
    assert not missing, f"frontend tabs missing backend route slugs: {missing}"


def test_tab_catchall_does_not_shadow_root_routes():
    """Regression: the /{session_id}/{tab} catch-all is a two-segment route, so it
    must NOT swallow two-segment ROOT paths (/api/status, /api/is-active-session,
    /static/*). It previously did, 307-redirecting them as session 'api'/'static'."""
    client = TestClient(app, follow_redirects=False)
    r = client.get("/api/status")
    assert r.status_code == 200, f"/api/status shadowed by tab route: {r.status_code}"
    assert "session_active" in r.json()
    r = client.get("/api/is-active-session")
    assert r.status_code == 200, f"/api/is-active-session shadowed: {r.status_code}"
    r = client.get("/static/common.css")
    assert r.status_code == 200, f"/static/common.css shadowed: {r.status_code}"
