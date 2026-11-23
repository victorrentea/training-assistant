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
         patch.object(SlidesRunner, "_start_redownload",
                      lambda self, slug, url, src, behind_only=False: started.append((slug, src, behind_only))):
        assert runner.scan_pptx_mtimes()
        assert started == []
        assert runner._deferred_prints == {"ae": deck}

        runner.scan_pptx_mtimes()  # still in front, nothing changed
        assert started == []

        frontmost[0] = False
        runner.scan_pptx_mtimes()
        assert started == [("ae", deck, True)], "started as a print that must stay behind"
        assert runner._deferred_prints == {}


def test_back_in_powerpoint_before_the_held_print_starts_it_waits_again(tmp_path):
    """The print thread may wait 20 s for another deck's print: by then he can be back."""
    from daemon.slides import local_publish
    from daemon.slides.loop import _run_redownload_poller

    deck = tmp_path / "ae.pptx"
    deck.write_bytes(b"x")
    runner = _runner(tmp_path, deck)
    ms = _misc()
    ms.slides_updated["ae"]["status"] = "downloading"  # as _start_redownload leaves it
    asked = []

    def attempt(slug, source, upload, in_front_ok=True):
        asked.append(in_front_ok)
        return "not_now"

    with patch("daemon.slides.router.misc_state", ms), \
         patch("daemon.slides.router._broadcast_slides_updated"), \
         patch("daemon.slides.router.download_on_railway") as google, \
         patch.object(local_publish, "attempt", attempt), \
         patch.object(save_origin, "powerpoint_frontmost", return_value=True):
        _run_redownload_poller("ae", "https://drive.test/ae", deck, lambda: runner._hold_back("ae", deck))

    assert asked == [False]
    assert runner._deferred_prints == {"ae": deck}
    assert ms.slides_updated["ae"]["status"] == "cached"
    google.assert_not_called()


def test_when_the_front_app_cannot_be_read_powerpoint_counts_as_in_front():
    """A print held back a little longer costs nothing; one under his hands does."""
    import subprocess

    def run(answers):
        calls = iter(answers)

        def fake(cmd, **kwargs):
            answer = next(calls)
            if isinstance(answer, Exception):
                raise answer
            return SimpleNamespace(returncode=answer[0], stdout=answer[1])
        return fake

    with patch.object(save_origin.sys, "platform", "darwin"):
        with patch.object(save_origin.subprocess, "run", run([subprocess.TimeoutExpired("lsappinfo", 5)])):
            assert save_origin.powerpoint_frontmost()
        with patch.object(save_origin.subprocess, "run", run([(0, "")])):
            assert save_origin.powerpoint_frontmost()
        with patch.object(save_origin.subprocess, "run", run([(0, "ASN:0x0-0x1:"), (1, "")])):
            assert save_origin.powerpoint_frontmost()
        with patch.object(save_origin.subprocess, "run",
                          run([(0, "ASN:0x0-0x1:"), (0, '"CFBundleIdentifier"="com.apple.Terminal"')])):
            assert not save_origin.powerpoint_frontmost()
        with patch.object(save_origin.subprocess, "run",
                          run([(0, "ASN:0x0-0x1:"), (0, '"CFBundleIdentifier"="com.microsoft.Powerpoint"')])):
            assert save_origin.powerpoint_frontmost()


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
         patch.object(SlidesRunner, "_start_redownload",
                      lambda self, slug, url, src, behind_only=False: started.append((slug, src, behind_only))):
        assert runner.scan_pptx_mtimes()
    assert started == [("ae", deck, False)], "his own save may print in front"
    assert runner._deferred_prints == {}
