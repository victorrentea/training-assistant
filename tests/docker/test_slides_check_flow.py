"""
Hermetic E2E test: PDF check/download flow via daemon ↔ Railway ↔ mock Drive.

Flow under test:
1. Participant calls GET /{sid}/api/slides/check/{slug} via daemon (port 8081)
2. Daemon sends download_pdf WS message to Railway
3. Railway downloads PDF from mock Google Drive
4. Railway sends pdf_download_complete WS back to daemon
5. Daemon resolves the pending /check → returns 200
6. Participant calls GET /{sid}/api/slides/download/{slug} on Railway (port 8000) → PDF bytes
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")

from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = os.environ.get("DAEMON_BASE", "http://localhost:8081")
MOCK_DRIVE = "http://localhost:9090"

# Hard-coded slug — first entry in the fixture catalog created by start_hermetic.sh
_SLUG = "clean-code"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _await_condition(fn, timeout_ms=10_000, poll_ms=300, msg=""):
    """Poll fn() until truthy or timeout."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(poll_ms / 1000)
    raise AssertionError(msg or f"Condition not met within {timeout_ms}ms")


def _check_slide(sid: str, slug: str, timeout_s: int = 35) -> int:
    """Call /check/{slug} via daemon. Returns HTTP status code."""
    url = f"{DAEMON_BASE}/{sid}/api/slides/check/{slug}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s + 2) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def _download_slide(sid: str, slug: str, base: str = BASE, timeout_s: int = 10) -> tuple[int, bytes]:
    """Download PDF from Railway. Returns (status_code, bytes)."""
    url = f"{base}/{sid}/api/slides/download/{slug}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def _mock_drive_stats() -> dict:
    with urllib.request.urlopen(f"{MOCK_DRIVE}/mock-drive/stats", timeout=3) as resp:
        return json.loads(resp.read())


def _mock_drive_reset_stats():
    req = urllib.request.Request(f"{MOCK_DRIVE}/mock-drive/reset-stats", method="POST", data=b"")
    urllib.request.urlopen(req, timeout=3)


def _mock_drive_set_delay(slug: str, delay_s: float):
    body = json.dumps({"slug": slug, "delay_s": delay_s}).encode()
    req = urllib.request.Request(
        f"{MOCK_DRIVE}/mock-drive/set-delay",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=body,
    )
    urllib.request.urlopen(req, timeout=5)


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


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_check_triggers_download_and_returns_200():
    """
    /check triggers a full download cycle and returns 200 once PDF is cached.

    Verifies:
    - /check blocks until Railway downloads the PDF from mock Drive
    - Returns 200 on success
    - Mock Drive received exactly 1 request for the slug
    - /download returns actual PDF bytes
    """
    sid = fresh_session("CheckFlow")
    _mock_drive_reset_stats()
    _mock_drive_reset_delays()

    print(f"[test1] Session: {sid}, slug: {_SLUG}")

    # /check should block until Railway fetches the PDF and notifies daemon
    status = _check_slide(sid, _SLUG, timeout_s=35)
    assert status == 200, f"Expected /check to return 200, got {status}"
    print(f"[test1] /check returned {status} ✓")

    # Exactly one request to mock Drive for this slug
    stats = _mock_drive_stats()
    count = stats.get(_SLUG, 0)
    assert count == 1, f"Expected exactly 1 mock Drive request for '{_SLUG}', got {count}. Stats: {stats}"
    print(f"[test1] Mock Drive request count for '{_SLUG}': {count} ✓")

    # /download returns a valid PDF
    dl_status, pdf_bytes = _download_slide(sid, _SLUG)
    assert dl_status == 200, f"Expected /download to return 200, got {dl_status}"
    assert pdf_bytes[:5] == b"%PDF-", f"Response is not a PDF: {pdf_bytes[:20]!r}"
    print(f"[test1] /download returned {len(pdf_bytes)} bytes of PDF ✓")


def test_check_returns_200_immediately_when_already_cached():
    """
    A second /check for an already-cached slug returns instantly (no re-download).

    Verifies:
    - /check returns 200 without a new Drive request
    - Response is faster than 2 seconds (cache hit is nearly instant)
    """
    sid = fresh_session("CheckCached")
    _mock_drive_reset_delays()

    print(f"[test2] Session: {sid}, slug: {_SLUG}")

    # Prime the cache — first /check triggers the download
    status_first = _check_slide(sid, _SLUG, timeout_s=35)
    assert status_first == 200, f"First /check returned {status_first}, expected 200"
    print(f"[test2] First /check returned {status_first} (download complete) ✓")

    # Reset stats so we can detect if another Drive request was made
    _mock_drive_reset_stats()

    # Second /check — should return immediately from cache
    t_start = time.monotonic()
    status_second = _check_slide(sid, _SLUG, timeout_s=35)
    elapsed_s = time.monotonic() - t_start

    assert status_second == 200, f"Second /check returned {status_second}, expected 200"
    assert elapsed_s < 2.0, (
        f"Second /check took {elapsed_s:.1f}s — expected a near-instant cache hit (<2s)"
    )
    print(f"[test2] Second /check returned {status_second} in {elapsed_s:.2f}s ✓")

    # No new Drive requests
    stats = _mock_drive_stats()
    count = stats.get(_SLUG, 0)
    assert count == 0, (
        f"Expected 0 new Drive requests on second /check (cached), got {count}. Stats: {stats}"
    )
    print(f"[test2] Mock Drive request count after second /check: {count} (no re-download) ✓")


def test_check_503_on_slow_drive_then_self_heals():
    """
    When Drive is too slow, /check times out with 503.
    After the delay is removed, Railway finishes the background download and
    /download eventually returns a valid PDF (self-heal).

    Verifies:
    - /check returns 503 when Drive takes longer than the 30s timeout
    - Railway completes the download in the background even after /check timed out
    - /download returns a valid PDF once the background download completes
    """
    sid = fresh_session("CheckSelfHeal")
    _mock_drive_reset_stats()
    _mock_drive_reset_delays()

    print(f"[test3] Session: {sid}, slug: {_SLUG}")

    # Set a 35s delay — longer than the /check 30s timeout
    _mock_drive_set_delay(_SLUG, 35)
    print(f"[test3] Set mock Drive delay to 35s for '{_SLUG}'")

    # /check should time out and return 503
    status = _check_slide(sid, _SLUG, timeout_s=35)
    assert status == 503, f"Expected /check to return 503 (timeout), got {status}"
    print(f"[test3] /check returned {status} (timeout as expected) ✓")

    # Remove the delay so Railway can finish the background download
    _mock_drive_reset_delays()
    print(f"[test3] Removed mock Drive delay — Railway should finish background download")

    # Poll /download until we get a PDF (or give up after 60s)
    def _pdf_available() -> bool:
        dl_status, pdf_bytes = _download_slide(sid, _SLUG, timeout_s=5)
        return dl_status == 200 and pdf_bytes[:5] == b"%PDF-"

    _await_condition(
        _pdf_available,
        timeout_ms=60_000,
        poll_ms=1000,
        msg=f"PDF for '{_SLUG}' never became available after removing Drive delay (self-heal failed)",
    )
    print(f"[test3] PDF available via /download after self-heal ✓")

    # Final verification: /download returns a real PDF
    dl_status, pdf_bytes = _download_slide(sid, _SLUG)
    assert dl_status == 200, f"Expected /download to return 200, got {dl_status}"
    assert pdf_bytes[:5] == b"%PDF-", f"Response is not a PDF: {pdf_bytes[:20]!r}"
    print(f"[test3] /download returned {len(pdf_bytes)} bytes of PDF after self-heal ✓")
