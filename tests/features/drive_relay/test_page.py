from fastapi.testclient import TestClient

from railway.app import app

client = TestClient(app)


def test_drive_page_is_served():
    response = client.get("/drive")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_page_carries_the_shared_csp():
    assert "default-src 'self'" in client.get("/drive").headers["content-security-policy"]


def test_page_never_points_the_browser_at_google():
    """Participants reaching this page cannot load anything from Google."""
    body = client.get("/drive").text

    assert "drive.google.com" not in body
    assert "googleapis.com" not in body
    assert "gstatic.com" not in body


def test_page_has_the_paste_field_and_button():
    body = client.get("/drive").text

    assert 'id="drive-url"' in body
    assert 'id="check-btn"' in body


def test_page_is_reachable_with_no_active_session():
    from railway.shared.state import state
    state.reset()

    assert client.get("/drive").status_code == 200
