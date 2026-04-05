"""Unit tests for startup slides catalog/cache initialization (daemon/slides/loop.py)."""
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from daemon.misc.state import MiscState
from daemon.slides.loop import SlidesPollingRunner


class _MainCfg:
    server_url = "https://example.test"
    host_username = "host"
    host_password = "pass"


def _runner_with_state() -> SlidesPollingRunner:
    runner = SlidesPollingRunner(_MainCfg())
    runner._slides_state = {"files": {}}
    return runner


def test_init_catalog_cache_status_uses_railway_availability():
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
            "drive_export_url": "https://docs.google.com/presentation/d/2/export/pdf",
        },
    ]

    with patch("daemon.slides.loop.misc_state", ms), \
         patch("daemon.slides.loop.load_catalog_entries", return_value=entries), \
         patch("daemon.slides.loop.get_active_session_id", return_value="sid123"), \
         patch("daemon.slides.loop._is_cached_on_railway", side_effect=[True, False]):
        runner._init_misc_state_from_catalog(cfg)

    assert ms.slides_catalog["reactive-webflux"]["title"] == "Reactive/WebFlux"
    assert ms.slides_catalog["caching"]["title"] == "Caching"
    assert ms.slides_cache_status["reactive-webflux"]["status"] == "cached"
    assert ms.slides_cache_status["caching"]["status"] == "not_cached"


def test_init_catalog_without_active_session_defaults_to_not_cached():
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
    ]

    with patch("daemon.slides.loop.misc_state", ms), \
         patch("daemon.slides.loop.load_catalog_entries", return_value=entries), \
         patch("daemon.slides.loop.get_active_session_id", return_value=None), \
         patch("daemon.slides.loop._is_cached_on_railway") as mocked_probe:
        runner._init_misc_state_from_catalog(cfg)

    mocked_probe.assert_not_called()
    assert ms.slides_cache_status["reactive-webflux"]["status"] == "not_cached"
