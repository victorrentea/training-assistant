"""Telling Victor Mac's auto-save from Victor's own ⌘S (daemon/slides/save_origin.py),
and holding the print after an auto-save while PowerPoint is in front (loop.py)."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from daemon.misc.state import MiscState
from daemon.slides import save_origin
from daemon.slides.loop import SlidesRunner


def _log(tmp_path: Path, entries: dict) -> Path:
    f = tmp_path / "saves.json"
    f.write_text(json.dumps(entries), encoding="utf-8")
    return f


def test_a_finished_scripted_save_matches_the_files_mtime(tmp_path):
    deck = tmp_path / "a.pptx"
    log = _log(tmp_path, {str(deck): {"started": 1000.0, "mtime": 1003.25}})
    assert save_origin.is_scripted_save(deck, 1003.25, log)
    assert not save_origin.is_scripted_save(deck, 1500.0, log)  # a later ⌘S


def test_a_save_under_way_counts_as_scripted(tmp_path):
    deck = tmp_path / "a.pptx"
    log = _log(tmp_path, {str(deck): {"started": 1000.0}})
    assert save_origin.is_scripted_save(deck, 1002.0, log)
    assert not save_origin.is_scripted_save(deck, 5000.0, log)


def test_another_deck_or_no_log_is_a_save_by_hand(tmp_path):
    log = _log(tmp_path, {str(tmp_path / "b.pptx"): {"started": 1000.0, "mtime": 1003.0}})
    assert not save_origin.is_scripted_save(tmp_path / "a.pptx", 1003.0, log)
    assert not save_origin.is_scripted_save(tmp_path / "a.pptx", 1003.0, tmp_path / "missing.json")


def test_the_same_deck_through_a_symlink_matches(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    log = _log(tmp_path, {str(tmp_path / "link" / "a.pptx"): {"started": 1.0, "mtime": 2.0}})
    assert save_origin.is_scripted_save(real / "a.pptx", 2.0, log)


class _MainCfg:
    server_url = "https://example.test"
    host_username = "host"
    host_password = "pass"


def _runner(tmp_path: Path, deck: Path) -> SlidesRunner:
    runner = SlidesRunner(_MainCfg())
    runner._slides_config = SimpleNamespace(state_file=str(tmp_path / "state.json"))
    runner._slides_state = {"files": {str(deck): {"slug": "ae", "pptx_mtime": 1.0}}}
    return runner


def _misc() -> MiscState:
    ms = MiscState()
    ms.slides_catalog = {"ae": {"drive_export_url": "https://drive.test/ae", "source_name": "ae.pptx"}}
    ms.slides_updated = {"ae": {"status": "cached"}}
    return ms


def test_an_auto_save_with_powerpoint_in_front_waits_then_prints_once_it_leaves(tmp_path):
    deck = tmp_path / "ae.pptx"
    deck.write_bytes(b"x")
    runner = _runner(tmp_path, deck)
    ms = _misc()
    frontmost = [True]
    started = []
    with patch("daemon.slides.loop.misc_state", ms), \
         patch("daemon.slides.loop.resolve_tracked_sources", return_value=([deck], {})), \
         patch("daemon.slides.loop.slides_daemon.save_daemon_state"), \
         patch("daemon.slides.export_probe.schedule_probe"), \
         patch.object(save_origin, "is_scripted_save", return_value=True), \
         patch.object(save_origin, "powerpoint_frontmost", side_effect=lambda: frontmost[0]), \
         patch.object(SlidesRunner, "_start_redownload", lambda self, slug, url, src: started.append((slug, src))):
        assert runner.scan_pptx_mtimes()
        assert started == []
        assert runner._deferred_prints == {"ae": deck}

        runner.scan_pptx_mtimes()  # still in front, nothing changed
        assert started == []

        frontmost[0] = False
        runner.scan_pptx_mtimes()
        assert started == [("ae", deck)]
        assert runner._deferred_prints == {}


def test_a_save_by_hand_prints_at_once_even_with_powerpoint_in_front(tmp_path):
    deck = tmp_path / "ae.pptx"
    deck.write_bytes(b"x")
    runner = _runner(tmp_path, deck)
    runner._deferred_prints = {"ae": deck}  # an earlier auto-save still waiting
    ms = _misc()
    started = []
    with patch("daemon.slides.loop.misc_state", ms), \
         patch("daemon.slides.loop.resolve_tracked_sources", return_value=([deck], {})), \
         patch("daemon.slides.loop.slides_daemon.save_daemon_state"), \
         patch("daemon.slides.export_probe.schedule_probe"), \
         patch.object(save_origin, "is_scripted_save", return_value=False), \
         patch.object(save_origin, "powerpoint_frontmost", return_value=True), \
         patch.object(SlidesRunner, "_start_redownload", lambda self, slug, url, src: started.append((slug, src))):
        assert runner.scan_pptx_mtimes()
    assert started == [("ae", deck)]
    assert runner._deferred_prints == {}
