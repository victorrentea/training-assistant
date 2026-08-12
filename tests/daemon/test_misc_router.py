"""Tests for daemon misc participant routes."""
import pytest
from unittest.mock import patch

from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.misc.router import participant_router
from daemon.misc.state import misc_state


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(participant_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_bug_report_quota():
    misc_state.bug_reports_sent.clear()
    yield
    misc_state.bug_reports_sent.clear()


def _post_bug_report(client, text="The slides tab is blank.", pid="p1", **diagnostics):
    return client.post(
        "/api/participant/misc/bug-report",
        json={"text": text, "diagnostics": diagnostics},
        headers={"X-Participant-ID": pid},
    )


def test_bug_report_emails_victor_with_the_report_and_diagnostics():
    client = _client()
    with patch("daemon.misc.router.email_notify", create=True, return_value=True) as notify:
        with patch.dict(
            "daemon.misc.router.participant_state.participant_names",
            {"p1": "Alice"},
            clear=True,
        ):
            resp = _post_bug_report(
                client,
                view="slides",
                user_agent="Mozilla/5.0 (iPhone)",
            )
    assert resp.status_code == 204
    assert resp.content == b""
    subject, body = notify.call_args.args
    assert "Alice" in subject
    assert "Reporter:    Alice" in body
    assert "Tab:         slides" in body
    assert "Daemon code:" in body
    assert "Mozilla/5.0 (iPhone)" in body
    assert "The slides tab is blank." in body
    assert notify.call_args.kwargs["from_inbox"] == "victor.flux@agentmail.to"


def test_bug_report_reporter_name_comes_from_the_server_not_the_request():
    """A report must not be signable as somebody else."""
    client = _client()
    with patch("daemon.misc.router.email_notify", create=True, return_value=True) as notify:
        with patch.dict(
            "daemon.misc.router.participant_state.participant_names",
            {"p1": "Alice", "p2": "Mallory"},
            clear=True,
        ):
            resp = client.post(
                "/api/participant/misc/bug-report",
                # Mallory tries to sign the report as Alice.
                json={"text": "Alice says this app is terrible.", "participant_name": "Alice"},
                headers={"X-Participant-ID": "p2"},
            )
    assert resp.status_code == 204
    subject, body = notify.call_args.args
    assert "Mallory" in subject
    assert "Reporter:    Mallory" in body
    assert "Alice" not in subject


def test_bug_report_strips_header_injection_from_diagnostics():
    """CRLF in attacker-controlled text must never reach a mail header."""
    client = _client()
    with patch("daemon.misc.router.email_notify", create=True, return_value=True) as notify:
        with patch.dict(
            "daemon.misc.router.participant_state.participant_names",
            {"p1": "Eve\r\nBcc: victim@example.com"},
            clear=True,
        ):
            resp = _post_bug_report(client, view="slides\r\nX-Injected: yes")
    assert resp.status_code == 204
    subject, body = notify.call_args.args
    # No line break survives, so "Bcc: …" stays inert text inside the subject
    # instead of becoming a header of its own.
    assert "\r" not in subject and "\n" not in subject
    assert len(subject.splitlines()) == 1
    assert "EveBcc: victim@example.com" in subject
    # The diagnostics block stays exactly one line per field — a smuggled newline
    # cannot forge an extra "Field: value" row (nor a header, once in a subject).
    header_block = body.split("── Report ──")[0]
    assert "\r" not in header_block
    assert len(header_block.strip().splitlines()) == 7
    assert "slidesX-Injected: yes" in header_block  # newline dropped, text kept


def test_bug_report_uses_active_session_name():
    client = _client()
    with patch("daemon.misc.router.email_notify", create=True, return_value=True) as notify:
        with patch(
            "daemon.session.state.get_active_session_name",
            return_value="2026-04-06 Architecture Masterclass",
        ):
            resp = _post_bug_report(client)
    assert resp.status_code == 204
    subject, body = notify.call_args.args
    assert "2026-04-06 Architecture Masterclass" in subject
    assert "Session:     2026-04-06 Architecture Masterclass" in body


def test_bug_report_requires_participant_id():
    client = _client()
    resp = client.post(
        "/api/participant/misc/bug-report",
        json={"text": "no id", "diagnostics": {}},
    )
    assert resp.status_code == 400


@pytest.mark.parametrize("text", ["", "   ", "x" * 5001])
def test_bug_report_rejects_empty_and_oversized_text(text):
    client = _client()
    with patch("daemon.misc.router.email_notify", create=True, return_value=True) as notify:
        resp = _post_bug_report(client, text=text)
    assert resp.status_code == 400
    notify.assert_not_called()


def test_bug_report_reports_a_failure_instead_of_a_false_confirmation():
    """When the mail transport is down the participant must be told."""
    client = _client()
    with patch("daemon.misc.router.email_notify", create=True, return_value=False):
        resp = _post_bug_report(client)
    assert resp.status_code == 503
    assert "Victor" in resp.json()["error"]
    # A failed send must not burn the participant's quota.
    assert misc_state.bug_reports_sent.get("p1", []) == []


def test_bug_report_throttles_a_participant_flooding_the_inbox():
    client = _client()
    with patch("daemon.misc.router.email_notify", create=True, return_value=True), \
         patch("daemon.misc.router.MIN_SECONDS_BETWEEN_BUG_REPORTS", 0):
        for _ in range(5):
            assert _post_bug_report(client).status_code == 204
        blocked = _post_bug_report(client)
    assert blocked.status_code == 429
    assert "limit" in blocked.json()["error"].lower()


def test_bug_report_enforces_a_minimum_gap_between_reports():
    client = _client()
    with patch("daemon.misc.router.email_notify", create=True, return_value=True):
        assert _post_bug_report(client).status_code == 204
        too_soon = _post_bug_report(client)
    assert too_soon.status_code == 429
    assert "fast" in too_soon.json()["error"].lower()


def test_bug_report_quota_resets_with_the_session():
    client = _client()
    with patch("daemon.misc.router.email_notify", create=True, return_value=True):
        assert _post_bug_report(client).status_code == 204
        assert _post_bug_report(client).status_code == 429
        misc_state.reset_for_new_session()
        assert _post_bug_report(client).status_code == 204


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
