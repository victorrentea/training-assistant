"""
Hermetic E2E regression test: participant sees slides list on first connect.

Bug: after PDF-caching-moved-to-daemon refactoring, Railway never populates
slides_cache_status, so participants received an empty slides list on connect.

Fix: daemon initializes misc_state from catalog on startup; participant JS
fetches GET /api/slides on WS connect (proxied to daemon).

This test verifies the fix without a browser by calling GET /api/slides directly.
"""

import json
import sys
import time
import urllib.request

import pytest

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/tests")
from session_utils import fresh_session

BASE = "http://localhost:8000"
DAEMON_BASE = "http://localhost:8081"

EXPECTED_SLUGS = {"clean-code", "design-patterns", "architecture"}


def test_slides_list_nonempty_after_connect():
    """GET /api/slides (proxied to daemon) returns the full catalog on first request.

    This test proves the bug is fixed: daemon populates misc_state.slides_catalog
    from the catalog file at startup, so the REST endpoint returns real data.
    """
    session_id = fresh_session("SlidesInitialSync")

    url = f"{BASE}/{session_id}/api/slides"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())

    slides = data.get("slides", [])
    slugs = {s.get("slug") for s in slides}

    assert len(slides) > 0, (
        f"Expected non-empty slides list from GET /api/slides — "
        f"daemon may not have initialized misc_state.slides_catalog from catalog file"
    )
    assert EXPECTED_SLUGS.issubset(slugs), (
        f"Expected slugs {EXPECTED_SLUGS} in slides list, got {slugs}"
    )


def test_slides_cache_status_included():
    """GET /api/slides includes cache_status for each slug in the catalog."""
    session_id = fresh_session("SlidesCacheStatus")

    url = f"{BASE}/{session_id}/api/slides"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())

    cache_status = data.get("cache_status", {})
    assert len(cache_status) > 0, (
        f"Expected non-empty cache_status from GET /api/slides — "
        f"daemon may not have initialized misc_state.slides_cache_status on startup"
    )
    for slug in EXPECTED_SLUGS:
        assert slug in cache_status, f"Expected slug '{slug}' in cache_status, got {cache_status.keys()}"
        status = cache_status[slug].get("status")
        assert status in ("cached", "not_cached", "error"), (
            f"Unexpected cache status for slug '{slug}': {status}"
        )
