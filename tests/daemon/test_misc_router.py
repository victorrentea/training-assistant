"""Tests for daemon misc participant routes."""
from unittest.mock import patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.misc.router import participant_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


def test_feedback_route_sends_email_notification():
    client = _client()
    with patch("daemon.misc.router.email_notify", create=True) as notify:
        resp = client.post(
            "/api/participant/misc/feedback",
            json={"text": "Please add dark mode toggle.", "participant_name": "Alice"},
            headers={"X-Participant-ID": "p1"},
        )
    assert resp.status_code == 204
    assert resp.content == b""
    notify.assert_called_once()
    subject, body = notify.call_args.args
    assert "Participant Feedback" in subject
    assert "Alice" in body
    assert "Please add dark mode toggle." in body


def test_feedback_route_falls_back_to_cached_participant_name():
    client = _client()
    with patch("daemon.misc.router.email_notify", create=True) as notify:
        with patch.dict(
            "daemon.misc.router.participant_state.participant_names",
            {"p3": "Bob"},
            clear=True,
        ):
            resp = client.post(
                "/api/participant/misc/feedback",
                json={"text": "Fallback name should work."},
                headers={"X-Participant-ID": "p3"},
            )
    assert resp.status_code == 204
    assert resp.content == b""
    _, body = notify.call_args.args
    assert "Participant: Bob" in body


def test_feedback_route_uses_active_session_name():
    client = _client()
    with patch("daemon.misc.router.email_notify", create=True) as notify:
        with patch(
            "daemon.session.state.get_active_session_name",
            return_value="2026-04-06 Architecture Masterclass",
        ):
            resp = client.post(
                "/api/participant/misc/feedback",
                json={"text": "Need bigger quiz buttons."},
                headers={"X-Participant-ID": "p2"},
            )
    assert resp.status_code == 204
    assert resp.content == b""
    subject, body = notify.call_args.args
    assert "2026-04-06 Architecture Masterclass" in subject
    assert "Session: 2026-04-06 Architecture Masterclass" in body


def _host_client() -> TestClient:
    from daemon.misc.router import host_router
    app = FastAPI()
    app.include_router(host_router)
    return TestClient(app)


def test_compilation_returns_204_when_no_slides_viewed():
    client = _host_client()
    with patch("daemon.misc.router.misc_state") as ms:
        ms.slides_viewed = []
        resp = client.get("/api/test-session/host/slides-compilation")
    assert resp.status_code == 204


def test_compilation_skips_file_with_no_catalog_entry():
    """If a slug from slides_viewed has no matching catalog entry, it is skipped."""
    client = _host_client()
    with patch("daemon.misc.router.misc_state") as ms:
        ms.slides_viewed = [{"slug": "unknown-abc", "page": 1, "seconds": 10}]
        ms.slides_catalog = {}
        ms.slides_updated = {}
        resp = client.get("/api/test-session/host/slides-compilation")
    assert resp.status_code == 204


def test_compilation_returns_pdf_for_cached_slide():
    """When all PDFs are already cached on Railway, returns a compiled PDF."""
    import io

    from pypdf import PdfWriter

    # Build a minimal valid 2-page PDF
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    client = _host_client()
    with patch("daemon.misc.router.misc_state") as ms, \
         patch("daemon.misc.router._fetch_pdf_bytes_from_railway", return_value=pdf_bytes) as fetch_mock, \
         patch("daemon.misc.router.asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
        ms.slides_viewed = [
            {"slug": "ai-coding-abc", "page": 1, "seconds": 30},
            {"slug": "ai-coding-abc", "page": 2, "seconds": 20},
        ]
        ms.slides_catalog = {
            "ai-coding-abc": {
                "drive_export_url": "https://gdrive.example.com/pdf",
            }
        }
        ms.slides_updated = {"ai-coding-abc": {"status": "cached"}}
        resp = client.get("/api/test-session/host/slides-compilation")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"%PDF")
    fetch_mock.assert_called_once_with("test-session", "ai-coding-abc")
