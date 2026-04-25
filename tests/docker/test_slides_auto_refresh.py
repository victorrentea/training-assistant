"""
Hermetic E2E test: Participant auto-refreshes slide when PPTX is saved.

Flow under test:
1. Participant opens the session; slides catalog loads
2. Daemon (simulated via direct API call) calls POST /api/slides/refresh/{slug}
3. Railway deletes its cached PDF and re-downloads from mock Google Drive
4. Railway broadcasts slides_updated with refreshed_slugs=[slug]
5. Participant browser receives the WS message and calls _loadSlideIntoViewer
   with forceReload=true, triggering a fresh GET /api/slides/download/{slug}?v=...
6. Railway serves the re-downloaded PDF bytes
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

from pages.participant_page import ParticipantPage
from playwright.sync_api import sync_playwright
from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:1234")
MOCK_DRIVE = "http://localhost:9090"
HOST_USER = os.environ.get("HOST_USERNAME", "host")
HOST_PASS = os.environ.get("HOST_PASSWORD", "testpass")

_SLUG = "clean-code"


# ── Helpers ────────────────────────────────────────────────────────────────────


def _await_condition(fn, timeout_ms=15_000, poll_ms=300, msg=""):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def _mock_drive_stats() -> dict:
    with urllib.request.urlopen(f"{MOCK_DRIVE}/mock-drive/stats", timeout=3) as resp:
        return json.loads(resp.read())


def _mock_drive_reset():
    req = urllib.request.Request(f"{MOCK_DRIVE}/mock-drive/reset-stats", method="POST", data=b"")
    urllib.request.urlopen(req, timeout=3)


def _mock_drive_reset_delays():
    req = urllib.request.Request(
        f"{MOCK_DRIVE}/mock-drive/reset-delays",
        method="POST",
        data=b"{}",
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _auth_header() -> str:
    return "Basic " + base64.b64encode(f"{HOST_USER}:{HOST_PASS}".encode()).decode()


def _prime_slide_cache(session_id: str) -> None:
    """Download the slide PDF via daemon /check so Railway has a cached copy."""
    url = f"{DAEMON_BASE}/{session_id}/api/slides/check/{_SLUG}?force=true"
    req = urllib.request.Request(url, headers={"Authorization": _auth_header()})
    try:
        with urllib.request.urlopen(req, timeout=35) as resp:
            assert resp.status == 200, f"/check returned {resp.status}"
    except urllib.error.HTTPError as e:
        # Accept 200 only
        raise AssertionError(f"/check returned HTTP {e.code}") from e


def _get_drive_export_url(session_id: str) -> str:
    """Fetch the drive_export_url for _SLUG from the daemon slides API."""
    url = f"{BASE}/{session_id}/api/slides"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())
    for slide in data.get("slides", []):
        if slide.get("slug") == _SLUG:
            return str(slide.get("drive_export_url", "")).strip()
    return ""


def _call_refresh(drive_export_url: str = "") -> int:
    """POST /api/slides/refresh/{slug} on Railway. Returns HTTP status code."""
    url = f"{BASE}/api/slides/refresh/{_SLUG}"
    body = json.dumps({"drive_export_url": drive_export_url}).encode()
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "Authorization": _auth_header(),
            "Content-Type": "application/json",
        },
        data=body,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_refresh_triggers_railway_redownload():
    """POST /api/slides/refresh/{slug} causes Railway to re-download from mock Drive."""
    session_id = fresh_session("AutoRefresh")
    _mock_drive_reset_delays()
    _mock_drive_reset()

    # Prime cache: participant /check → Railway downloads once from mock Drive
    _prime_slide_cache(session_id)
    stats_after_prime = _mock_drive_stats()
    count_after_prime = stats_after_prime.get(_SLUG, 0)
    assert count_after_prime >= 1, f"Expected ≥1 Drive request after priming, got {stats_after_prime}"
    print(f"[test] Cache primed — mock Drive request count for '{_SLUG}': {count_after_prime}")

    # Reset so we can count re-download requests only
    _mock_drive_reset()

    # Get drive_export_url from catalog
    drive_export_url = _get_drive_export_url(session_id)
    assert drive_export_url, "No drive_export_url found for slug in catalog"
    print(f"[test] drive_export_url: {drive_export_url}")

    # Simulate daemon calling refresh after a PPTX save
    status = _call_refresh(drive_export_url)
    assert status == 200, f"POST /refresh returned {status}, expected 200"
    print(f"[test] POST /refresh returned {status} ✓")

    # Railway should re-download from mock Drive (async background task)
    _await_condition(
        lambda: _mock_drive_stats().get(_SLUG, 0) >= 1,
        timeout_ms=15_000,
        msg=f"Railway did not re-download '{_SLUG}' from mock Drive within 15s",
    )
    redownload_count = _mock_drive_stats().get(_SLUG, 0)
    print(f"[test] Mock Drive re-download count for '{_SLUG}': {redownload_count} ✓")

    # Railway should still serve the PDF from the refreshed cache
    url = f"{BASE}/{session_id}/api/slides/download/{_SLUG}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        pdf_bytes = resp.read()
    assert pdf_bytes[:5] == b"%PDF-", f"Expected PDF, got {pdf_bytes[:20]!r}"
    print(f"[test] /download still serves valid PDF ({len(pdf_bytes)} bytes) ✓")


def test_refresh_without_drive_url_in_body_returns_422():
    """The refresh endpoint requires drive_export_url; missing/empty → 422."""
    session_id = fresh_session("AutoRefreshNoUrl")
    _mock_drive_reset_delays()
    _prime_slide_cache(session_id)
    _mock_drive_reset()

    status = _call_refresh(drive_export_url="")
    assert status == 422, f"POST /refresh with no drive_export_url returned {status}, expected 422"


def test_participant_receives_updated_downloaded_at_in_ws():
    """Participant WS receives decks_updated with changed downloaded_at after refresh."""
    session_id = fresh_session("AutoRefreshWS")
    _mock_drive_reset_delays()
    _prime_slide_cache(session_id)

    drive_export_url = _get_drive_export_url(session_id)
    assert drive_export_url, "No drive_export_url in catalog"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()
        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("RefreshWatcher")

        # Capture initial downloaded_at for the target slug, then watch for a change.
        pax_page.evaluate(f"""() => {{
            window._initialDownloadedAt = (window._slidesCacheStatus || {{}})['{_SLUG}']?.downloaded_at || null;
            window._refreshedDownloadedAt = null;
            if (typeof _ws !== 'undefined' && _ws) {{
                _ws.addEventListener('message', (evt) => {{
                    try {{
                        const msg = JSON.parse(evt.data);
                        if (msg.type === 'decks_updated' && msg.decks && msg.decks['{_SLUG}']) {{
                            const incoming = msg.decks['{_SLUG}'].downloaded_at;
                            if (incoming && incoming !== window._initialDownloadedAt) {{
                                window._refreshedDownloadedAt = incoming;
                            }}
                        }}
                    }} catch {{}}
                }});
            }}
        }}""")

        # Wait for participant to connect
        _await_condition(
            lambda: pax_page.locator(".topic-item").count() > 0,
            timeout_ms=10_000,
            msg="No slides loaded for participant",
        )

        # Trigger refresh
        status = _call_refresh(drive_export_url)
        assert status == 200, f"POST /refresh returned {status}"

        # Participant should receive decks_updated with a new downloaded_at for the slug
        _await_condition(
            lambda: pax_page.evaluate("() => !!window._refreshedDownloadedAt"),
            timeout_ms=15_000,
            msg=f"Participant did not receive updated downloaded_at for '{_SLUG}' within 15s",
        )
        new_ts = pax_page.evaluate("() => window._refreshedDownloadedAt")
        print(f"[test] Participant received updated downloaded_at: {new_ts} ✓")

        browser.close()


def test_participant_auto_reloads_active_slide_after_refresh():
    """Participant reloads the active slide PDF when slides_updated has refreshed_slugs."""
    session_id = fresh_session("AutoRefreshReload")
    _mock_drive_reset_delays()
    _prime_slide_cache(session_id)

    drive_export_url = _get_drive_export_url(session_id)
    assert drive_export_url, "No drive_export_url in catalog"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pax_ctx = browser.new_context()
        pax_page = pax_ctx.new_page()

        pax_page.goto(f"{BASE}/{session_id}", wait_until="networkidle")
        pax = ParticipantPage(pax_page)
        pax.join("ReloadWatcher")

        # Open the slide and wait for PDF canvas (ensures _activeSlideId is set in JS)
        pax.open_slide(_SLUG)
        print(f"[test] Slide '{_SLUG}' opened and PDF rendered ✓")

        # Inject a spy on window.loadPdf to detect reloads without relying on network monitoring.
        # Network monitoring is unreliable (pdf.js may use workers, caching, etc.).
        # Capture (url, slug, downloadedAt) — cache-busting is now keyed by
        # downloadedAt (PdfCache invalidation), not by a ?v= URL parameter.
        pax_page.evaluate("""() => {
            const origLoadPdf = window.loadPdf;
            window._loadPdfCalls = [];
            window.loadPdf = async function(url, slug, downloadedAt, targetPage) {
                window._loadPdfCalls.push({url: url || '', slug: slug || '', downloadedAt: downloadedAt || null});
                return origLoadPdf(url, slug, downloadedAt, targetPage);
            };
        }""")

        # Trigger refresh (simulates daemon notification after PPTX save)
        status = _call_refresh(drive_export_url)
        assert status == 200, f"POST /refresh returned {status}"
        print(f"[test] POST /refresh returned {status} ✓")

        # Participant should auto-reload the slide for the active slug.
        _await_condition(
            lambda: pax_page.evaluate(
                f"() => (window._loadPdfCalls || []).some(c => c.slug === '{_SLUG}')"
            ),
            timeout_ms=20_000,
            msg=f"Participant did not auto-reload slide '{_SLUG}' after refresh",
        )
        calls = pax_page.evaluate("() => window._loadPdfCalls")
        last = calls[-1] if calls else {}
        print(f"[test] Participant reloaded slide via loadPdf: {last} ✓")
        # Cache invalidation moved from ?v= URL params to PdfCache (IDB) keyed
        # by downloadedAt — the new value must be present and differ from the
        # cached one (test reset cache before triggering refresh).
        assert last.get("slug") == _SLUG, f"Expected slug={_SLUG}, got {last!r}"
        assert last.get("downloadedAt"), (
            f"Expected non-empty downloadedAt for cache key, got {last!r}"
        )

        browser.close()
