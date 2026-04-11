"""Unit tests for startup slides catalog/cache initialization (daemon/slides/loop.py)."""
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from daemon.misc.state import MiscState
from daemon.slides.loop import SlidesRunner


class _MainCfg:
    server_url = "https://example.test"
    host_username = "host"
    host_password = "pass"


def _runner_with_state() -> SlidesRunner:
    runner = SlidesRunner(_MainCfg())
    runner._slides_state = {"files": {}}
    return runner


def test_init_catalog_marks_all_not_cached():
    """At startup, _init_misc_state_from_catalog marks all slugs as not_cached
    (actual cache status is probed on WS connect via probe_railway_cache)."""
    runner = _runner_with_state()
    cfg = SimpleNamespace(catalog_file="unused", server_url="https://example.test")
    ms = MiscState()

    entries = [
        {
            "source": Path("/tmp/Reactive-WebFlux.pptx"),
            "target_pdf": "Reactive-WebFlux.pdf",
            "title": "Reactive/WebFlux",
            "drive_export_url": "https://docs.google.com/presentation/d/1/export/pdf",
        },
        {
            "source": Path("/tmp/Caching.pptx"),
            "target_pdf": "Caching.pdf",
            "title": "Caching",
            "group": "Architecture",
            "drive_export_url": "https://docs.google.com/presentation/d/2/export/pdf",
        },
    ]

    with patch("daemon.slides.loop.misc_state", ms), \
         patch("daemon.slides.loop.load_catalog_entries", return_value=entries):
        runner._init_misc_state_from_catalog(cfg)

    assert ms.slides_catalog["reactive-webflux"]["title"] == "Reactive/WebFlux"
    assert ms.slides_catalog["caching"]["title"] == "Caching"
    assert ms.slides_catalog["caching"]["group"] == "Architecture"
    assert ms.slides_cache_status["reactive-webflux"]["status"] == "not_cached"
    assert ms.slides_cache_status["caching"]["status"] == "not_cached"


def test_probe_railway_cache_updates_status():
    """probe_railway_cache() HEAD-checks Railway and updates slides_cache_status."""
    runner = _runner_with_state()
    ms = MiscState()
    ms.slides_catalog = {
        "reactive-webflux": {"slug": "reactive-webflux", "title": "Reactive/WebFlux"},
        "caching": {"slug": "caching", "title": "Caching"},
    }
    ms.slides_cache_status = {
        "reactive-webflux": {"status": "not_cached"},
        "caching": {"status": "not_cached"},
    }

    with patch("daemon.slides.loop.misc_state", ms), \
         patch("daemon.slides.loop.get_active_session_id", return_value="sid123"), \
         patch("daemon.slides.loop._is_cached_on_railway", side_effect=[True, False]), \
         patch("daemon.slides.router._broadcast_slides_cache_status"):
        runner.probe_railway_cache()

    assert ms.slides_cache_status["reactive-webflux"]["status"] == "cached"
    assert ms.slides_cache_status["caching"]["status"] == "not_cached"


def test_probe_railway_cache_skips_without_session():
    """probe_railway_cache() does nothing when no session is active."""
    runner = _runner_with_state()
    ms = MiscState()
    ms.slides_catalog = {"slug1": {"slug": "slug1"}}
    ms.slides_cache_status = {"slug1": {"status": "not_cached"}}

    with patch("daemon.slides.loop.misc_state", ms), \
         patch("daemon.slides.loop.get_active_session_id", return_value=None), \
         patch("daemon.slides.loop._is_cached_on_railway") as mocked_probe:
        runner.probe_railway_cache()

    mocked_probe.assert_not_called()
    assert ms.slides_cache_status["slug1"]["status"] == "not_cached"
