"""Contract tests for participant HTML page routing (tabs + relocated notes page)."""

from fastapi.testclient import TestClient

from railway.app import app, state

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
