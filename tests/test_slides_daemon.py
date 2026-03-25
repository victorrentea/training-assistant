import json
import os
from pathlib import Path

import slides_daemon


def _cfg(tmp_path: Path) -> slides_daemon.SlidesDaemonConfig:
    return slides_daemon.SlidesDaemonConfig(
        watch_dir=tmp_path / "watch",
        poll_interval_seconds=30.0,
        min_cpu_free_percent=25.0,
        state_file=tmp_path / "state.json",
        work_dir=tmp_path / "work",
        server_url="https://interact.example.com",
        host_username="host",
        host_password="secret",
        converter="libreoffice",
        upload_mode="copy",
        public_base_url="https://slides.example.com",
        publish_dir=tmp_path / "publish",
        recursive=False,
    )


def test_ensure_slug_is_persistent_for_same_file(tmp_path):
    path = tmp_path / "deck.pptx"
    path.write_bytes(b"pptx")
    state = {"files": {}}

    slug1 = slides_daemon.ensure_slug(state, path)
    slug2 = slides_daemon.ensure_slug(state, path)

    assert slug1 == slug2
    assert len(slug1) == 32


def test_detect_changed_files_uses_last_exported_mtime(tmp_path):
    watch = tmp_path / "watch"
    watch.mkdir()
    a = watch / "a.pptx"
    b = watch / "b.pptx"
    a.write_bytes(b"a")
    b.write_bytes(b"b")

    state = {
        "files": {
            str(a.resolve()): {"slug": "x", "last_exported_mtime": a.stat().st_mtime},
            str(b.resolve()): {"slug": "y", "last_exported_mtime": b.stat().st_mtime - 5.0},
        }
    }
    changed = slides_daemon.detect_changed_files([a, b], state)
    assert changed == [b]


def test_process_one_file_skips_when_cpu_is_busy(tmp_path, monkeypatch, capsys):
    watch = tmp_path / "watch"
    watch.mkdir()
    deck = watch / "deck.pptx"
    deck.write_bytes(b"x")

    cfg = _cfg(tmp_path)
    state = {"files": {}}

    monkeypatch.setattr(slides_daemon, "get_cpu_free_percent", lambda sample_seconds=1.0: 10.0)

    called = {"convert": False, "upload": False, "push": False}

    def _mark_convert(*args, **kwargs):
        called["convert"] = True
        return tmp_path / "out.pdf"

    def _mark_upload(*args, **kwargs):
        called["upload"] = True
        return "https://slides.example.com/z.pdf"

    def _mark_push(*args, **kwargs):
        called["push"] = True

    monkeypatch.setattr(slides_daemon, "convert_pptx_to_pdf", _mark_convert)
    monkeypatch.setattr(slides_daemon, "upload_pdf", _mark_upload)
    monkeypatch.setattr(slides_daemon, "push_current_slides", _mark_push)

    processed = slides_daemon.process_one_file(cfg, state, deck)
    captured = capsys.readouterr()

    assert processed is False
    assert "CPU overloaded" in captured.out
    assert called == {"convert": False, "upload": False, "push": False}


def test_process_one_file_updates_state_and_persists(tmp_path, monkeypatch):
    watch = tmp_path / "watch"
    watch.mkdir()
    deck = watch / "deck.pptx"
    deck.write_bytes(b"x")

    cfg = _cfg(tmp_path)
    state = {"files": {}}
    out_pdf = tmp_path / "work" / "deck.pdf"
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    out_pdf.write_bytes(b"%PDF")

    monkeypatch.setattr(slides_daemon, "get_cpu_free_percent", lambda sample_seconds=1.0: 80.0)
    monkeypatch.setattr(slides_daemon, "convert_pptx_to_pdf", lambda *args, **kwargs: out_pdf)
    monkeypatch.setattr(
        slides_daemon,
        "upload_pdf",
        lambda *args, **kwargs: "https://slides.example.com/published.pdf",
    )

    pushed = {}

    def _fake_push(config, public_url, slug, source_file):
        pushed["url"] = public_url
        pushed["slug"] = slug
        pushed["source_file"] = source_file

    monkeypatch.setattr(slides_daemon, "push_current_slides", _fake_push)

    saved = {}

    def _fake_save(path, data):
        saved["path"] = path
        saved["data"] = data

    monkeypatch.setattr(slides_daemon, "save_daemon_state", _fake_save)

    processed = slides_daemon.process_one_file(cfg, state, deck)

    key = str(deck.resolve())
    assert processed is True
    assert key in state["files"]
    assert state["files"][key]["slug"]
    assert state["files"][key]["last_exported_mtime"] == deck.stat().st_mtime
    assert pushed["url"] == "https://slides.example.com/published.pdf"
    assert pushed["source_file"] == "deck.pptx"
    assert saved["path"] == cfg.state_file


def test_run_once_processes_single_oldest_changed_file(tmp_path, monkeypatch):
    watch = tmp_path / "watch"
    watch.mkdir()
    a = watch / "a.pptx"
    b = watch / "b.pptx"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    # Force deterministic mtimes
    os.utime(a, (1000, 1000))
    os.utime(b, (2000, 2000))

    cfg = _cfg(tmp_path)
    state = {"files": {}}
    seen = []

    def _fake_process(config, daemon_state, pptx, target_pdf=None):
        seen.append(pptx.name)
        key = str(pptx.resolve())
        daemon_state.setdefault("files", {}).setdefault(key, {})
        daemon_state["files"][key]["last_exported_mtime"] = pptx.stat().st_mtime
        daemon_state["files"][key]["slug"] = "x"
        return True

    monkeypatch.setattr(slides_daemon, "process_one_file", _fake_process)
    changed = slides_daemon.run_once(cfg, state)
    assert changed is True
    assert seen == ["a.pptx"]


def test_load_catalog_entries_and_resolve_targets(tmp_path):
    watch = tmp_path / "watch"
    watch.mkdir()
    deck = watch / "deck.pptx"
    deck.write_bytes(b"x")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "decks": [
                    {
                        "title": "Deck",
                        "source": str(deck),
                        "target_pdf": "Deck Final.pdf",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    cfg = _cfg(tmp_path)
    cfg.catalog_file = catalog
    files, metadata = slides_daemon.resolve_tracked_sources(cfg)
    assert files == [deck]
    meta = metadata[str(deck.resolve())]
    assert meta["title"] == "Deck"
    assert meta["target_pdf"] == "Deck Final.pdf"


def test_run_once_uses_catalog_target_pdf(tmp_path, monkeypatch):
    watch = tmp_path / "watch"
    watch.mkdir()
    deck = watch / "deck.pptx"
    deck.write_bytes(b"x")
    os.utime(deck, (2000, 2000))
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "decks": [
                    {
                        "title": "Deck",
                        "source": str(deck),
                        "target_pdf": "Deck Final.pdf",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    cfg = _cfg(tmp_path)
    cfg.catalog_file = catalog
    state = {"files": {}}
    captured = {}

    def _fake_process(config, daemon_state, pptx, target_pdf=None):
        captured["source"] = pptx
        captured["target_pdf"] = target_pdf
        return True

    monkeypatch.setattr(slides_daemon, "process_one_file", _fake_process)
    changed = slides_daemon.run_once(cfg, state)
    assert changed is True
    assert captured["source"] == deck
    assert captured["target_pdf"] == "Deck Final.pdf"
