import json
import os
from pathlib import Path

import pytest
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
        post_export_cooldown_seconds=5.0,
        failure_retry_seconds=60.0,
        drive_sync_timeout_seconds=90.0,
        drive_poll_seconds=5.0,
        drive_stable_probes=2,
        drive_bootstrap_url="https://victorrentea.ro/slides/",
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


def test_detect_changed_files_does_not_trigger_when_target_pdf_missing(tmp_path):
    watch = tmp_path / "watch"
    watch.mkdir()
    publish = tmp_path / "publish"
    publish.mkdir()
    a = watch / "a.pptx"
    a.write_bytes(b"a")
    state = {
        "files": {
            str(a.resolve()): {"slug": "x", "last_exported_mtime": a.stat().st_mtime},
        }
    }
    metadata = {str(a.resolve()): {"target_pdf": "A.pdf"}}
    changed = slides_daemon.detect_changed_files([a], state, metadata=metadata, publish_dir=publish)
    assert changed == []


def test_detect_changed_files_uses_lastmodified_marker(tmp_path):
    watch = tmp_path / "watch"
    watch.mkdir()
    publish = tmp_path / "publish"
    publish.mkdir()
    a = watch / "a.pptx"
    a.write_bytes(b"a")
    os.utime(a, (2000, 2000))

    marker = publish / "A.pdf.lastmodified"
    marker.write_text("2000.0\n", encoding="utf-8")

    state = {"files": {str(a.resolve()): {"slug": "x", "last_exported_mtime": 1000.0}}}
    metadata = {str(a.resolve()): {"target_pdf": "A.pdf"}}
    changed = slides_daemon.detect_changed_files([a], state, metadata=metadata, publish_dir=publish)
    assert changed == []

    marker.write_text("1500.0\n", encoding="utf-8")
    changed = slides_daemon.detect_changed_files([a], state, metadata=metadata, publish_dir=publish)
    assert changed == [a]


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


def test_process_one_file_writes_lastmodified_marker(tmp_path, monkeypatch):
    watch = tmp_path / "watch"
    watch.mkdir()
    deck = watch / "deck.pptx"
    deck.write_bytes(b"x")

    cfg = _cfg(tmp_path)
    cfg.sync_backend = False
    state = {"files": {}}
    out_pdf = tmp_path / "work" / "deck.pdf"
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    out_pdf.write_bytes(b"%PDF")

    monkeypatch.setattr(slides_daemon, "get_cpu_free_percent", lambda sample_seconds=1.0: 80.0)
    monkeypatch.setattr(slides_daemon, "convert_pptx_to_pdf", lambda *args, **kwargs: out_pdf)
    monkeypatch.setattr(slides_daemon, "upload_pdf", lambda *args, **kwargs: str(cfg.publish_dir / "Deck.pdf"))

    processed = slides_daemon.process_one_file(cfg, state, deck, target_pdf="Deck.pdf")
    assert processed is True
    marker = cfg.publish_dir / "Deck.pdf.lastmodified"
    assert marker.exists()
    assert float(marker.read_text(encoding="utf-8").strip()) == deck.stat().st_mtime


def test_run_once_processes_single_oldest_changed_file(tmp_path, monkeypatch, capsys):
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

    def _fake_process(config, daemon_state, pptx, target_pdf=None, metadata=None):
        seen.append(pptx.name)
        key = str(pptx.resolve())
        daemon_state.setdefault("files", {}).setdefault(key, {})
        daemon_state["files"][key]["last_exported_mtime"] = pptx.stat().st_mtime
        daemon_state["files"][key]["slug"] = "x"
        return True

    monkeypatch.setattr(slides_daemon, "process_one_file", _fake_process)
    monkeypatch.setattr(slides_daemon, "sync_slides_list", lambda *_args, **_kwargs: False)
    changed = slides_daemon.run_once(cfg, state)
    out = capsys.readouterr().out
    assert changed is True
    assert seen == ["a.pptx"]
    assert "✏️ppt update detected => regenerating ppf: a.pptx" in out


def test_run_once_respects_post_export_cooldown(tmp_path, monkeypatch, capsys):
    watch = tmp_path / "watch"
    watch.mkdir()
    deck = watch / "deck.pptx"
    deck.write_bytes(b"x")
    os.utime(deck, (2000, 2000))

    cfg = _cfg(tmp_path)
    cfg.post_export_cooldown_seconds = 5.0
    state = {"files": {}, "last_export_finished_at": 100.0}

    monkeypatch.setattr(slides_daemon.time, "time", lambda: 103.0)
    monkeypatch.setattr(slides_daemon, "process_one_file", lambda *args, **kwargs: True)
    monkeypatch.setattr(slides_daemon, "sync_slides_list", lambda *_args, **_kwargs: False)

    changed = slides_daemon.run_once(cfg, state)
    out = capsys.readouterr().out

    assert changed is False
    assert "Cooldown active (2.0s remaining)" in out


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

    def _fake_process(config, daemon_state, pptx, target_pdf=None, metadata=None):
        captured["source"] = pptx
        captured["target_pdf"] = target_pdf
        captured["metadata"] = metadata
        return True

    monkeypatch.setattr(slides_daemon, "process_one_file", _fake_process)
    monkeypatch.setattr(slides_daemon, "sync_slides_list", lambda *_args, **_kwargs: False)
    changed = slides_daemon.run_once(cfg, state)
    assert changed is True
    assert captured["source"] == deck
    assert captured["target_pdf"] == "Deck Final.pdf"
    assert captured["metadata"]["target_pdf"] == "Deck Final.pdf"


def test_run_once_pushes_slides_list_only_when_payload_changes(tmp_path, monkeypatch):
    watch = tmp_path / "watch"
    watch.mkdir()
    publish = tmp_path / "publish"
    publish.mkdir()
    intro = publish / "Intro.pdf"
    intro.write_bytes(b"%PDF-1.4 intro")

    cfg = _cfg(tmp_path)
    state = {"files": {}}
    posted = []

    monkeypatch.setattr(
        slides_daemon,
        "_post_json",
        lambda url, payload, *_args, **_kwargs: posted.append((url, payload)) or {"ok": True},
    )

    changed = slides_daemon.run_once(cfg, state)
    assert changed is True
    assert len(posted) == 1
    assert posted[0][0].endswith("/api/quiz-status")
    assert posted[0][1]["status"] == "ready"
    assert len(posted[0][1]["slides"]) == 1
    assert posted[0][1]["slides"][0]["name"] == "Intro"

    changed = slides_daemon.run_once(cfg, state)
    assert changed is False
    assert len(posted) == 1

    newer = intro.stat().st_mtime + 5.0
    os.utime(intro, (newer, newer))
    changed = slides_daemon.run_once(cfg, state)
    assert changed is True
    assert len(posted) == 2


def test_run_once_republishes_list_when_pdf_deleted(tmp_path, monkeypatch):
    watch = tmp_path / "watch"
    watch.mkdir()
    publish = tmp_path / "publish"
    publish.mkdir()
    a = publish / "A.pdf"
    b = publish / "B.pdf"
    a.write_bytes(b"%PDF-a")
    b.write_bytes(b"%PDF-b")

    cfg = _cfg(tmp_path)
    state = {"files": {}}
    posted = []

    monkeypatch.setattr(
        slides_daemon,
        "_post_json",
        lambda url, payload, *_args, **_kwargs: posted.append((url, payload)) or {"ok": True},
    )

    assert slides_daemon.run_once(cfg, state) is True
    assert len(posted[-1][1]["slides"]) == 2

    b.unlink()
    assert slides_daemon.run_once(cfg, state) is True
    assert len(posted[-1][1]["slides"]) == 1


def test_config_defaults_publish_dir_to_materials_slides(tmp_path, monkeypatch):
    materials = tmp_path / "materials"
    materials.mkdir()
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"decks": []}), encoding="utf-8")

    monkeypatch.setenv("MATERIALS_FOLDER", str(materials))
    monkeypatch.setenv("PPTX_CATALOG_FILE", str(catalog))
    monkeypatch.delenv("PPTX_PUBLISH_DIR", raising=False)
    monkeypatch.setenv("PPTX_SYNC_BACKEND", "0")

    cfg = slides_daemon.config_from_env()
    assert cfg.publish_dir == materials / "slides"


def test_convert_with_libreoffice_falls_back_to_macos_app_binary(tmp_path, monkeypatch):
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"x")
    out_dir = tmp_path / "out"
    app_bin = "/Applications/LibreOffice.app/Contents/MacOS/soffice"

    monkeypatch.setattr(slides_daemon.shutil, "which", lambda _name: None)

    real_exists = slides_daemon.os.path.exists

    def _fake_exists(path):
        if path == app_bin:
            return True
        return real_exists(path)

    monkeypatch.setattr(slides_daemon.os.path, "exists", _fake_exists)

    seen = {}

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, capture_output=True, text=True):
        seen["cmd"] = cmd
        (out_dir / "deck.pdf").write_bytes(b"%PDF")
        return _Proc()

    monkeypatch.setattr(slides_daemon.subprocess, "run", _fake_run)

    pdf = slides_daemon.convert_with_libreoffice(pptx, out_dir)
    assert pdf == out_dir / "deck.pdf"
    assert seen["cmd"][0] == app_bin


def test_convert_with_libreoffice_accepts_stdout_reported_pdf_when_name_differs(tmp_path, monkeypatch):
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"x")
    out_dir = tmp_path / "out"
    app_bin = "/Applications/LibreOffice.app/Contents/MacOS/soffice"

    monkeypatch.setattr(slides_daemon.shutil, "which", lambda _name: None)
    real_exists = slides_daemon.os.path.exists

    def _fake_exists(path):
        if path == app_bin:
            return True
        return real_exists(path)

    monkeypatch.setattr(slides_daemon.os.path, "exists", _fake_exists)
    monkeypatch.setattr(slides_daemon.time, "time", lambda: 1000.0)

    class _Proc:
        returncode = 0
        stdout = "convert /tmp/deck.pptx -> /tmp/out/deck_exported.pdf using filter : writer_pdf_Export"
        stderr = ""

    def _fake_run(cmd, capture_output=True, text=True):
        (out_dir / "deck_exported.pdf").parent.mkdir(parents=True, exist_ok=True)
        (out_dir / "deck_exported.pdf").write_bytes(b"%PDF")
        return _Proc()

    monkeypatch.setattr(slides_daemon.subprocess, "run", _fake_run)

    pdf = slides_daemon.convert_with_libreoffice(pptx, out_dir)
    assert pdf == out_dir / "deck_exported.pdf"


def test_convert_with_libreoffice_raises_when_source_not_loaded_even_with_exit_zero(tmp_path, monkeypatch):
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"x")
    out_dir = tmp_path / "out"
    app_bin = "/Applications/LibreOffice.app/Contents/MacOS/soffice"

    monkeypatch.setattr(slides_daemon.shutil, "which", lambda _name: None)
    real_exists = slides_daemon.os.path.exists
    monkeypatch.setattr(slides_daemon.os.path, "exists", lambda p: True if p == app_bin else real_exists(p))

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = "Error: source file could not be loaded"

    monkeypatch.setattr(slides_daemon.subprocess, "run", lambda *args, **kwargs: _Proc())

    with pytest.raises(RuntimeError, match="source file could not be loaded"):
        slides_daemon.convert_with_libreoffice(pptx, out_dir)


def test_extract_drive_export_links_from_html():
    html = """
    <html><body>
      <a href="https://docs.google.com/presentation/d/abc123/edit">AI Coding</a>
      <a href="https://docs.google.com/presentation/d/def456/preview">Reactive WebFlux</a>
      <a href="https://example.com/nope">Other</a>
    </body></html>
    """
    links = slides_daemon.extract_drive_export_links(html)
    assert links["AI Coding"] == "https://docs.google.com/presentation/d/abc123/export/pdf"
    assert links["Reactive WebFlux"] == "https://docs.google.com/presentation/d/def456/export/pdf"
    assert "Other" not in links


def test_bootstrap_drive_urls_uses_alias_map(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "decks": [
                    {
                        "title": "Reactive/WebFlux",
                        "source": "/tmp/reactive.pptx",
                        "target_pdf": "Reactive WebFlux.pdf",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    html = """
    <a href="https://docs.google.com/presentation/d/reactive123/edit">Reactive WebFlux</a>
    """
    monkeypatch.setattr(slides_daemon, "_read_url_text", lambda *_args, **_kwargs: html)

    updated, missing = slides_daemon.bootstrap_drive_urls(catalog, "https://victorrentea.ro/slides/")
    assert updated == 2
    assert missing == 0

    data = json.loads(catalog.read_text(encoding="utf-8"))
    entry = data["decks"][0]
    assert entry["drive_export_url"] == "https://docs.google.com/presentation/d/reactive123/export/pdf"
    assert entry["drive_probe_url"] == "https://docs.google.com/presentation/d/reactive123/export/pdf"


def test_google_drive_pull_single_fetch_accepts_new_fingerprint(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.converter = "google_drive_pull"
    downloaded = {"called": 0}
    monkeypatch.setattr(slides_daemon.time, "time", lambda: 1000.0)

    def _fake_download(_url, out):
        downloaded["called"] += 1
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"%PDF-1.4 NEW")
        return out

    monkeypatch.setattr(slides_daemon, "_download_pdf_from_url", _fake_download)

    out = tmp_path / "work" / "deck.pdf"
    state_entry = {"last_drive_fingerprint": "pdf:old"}
    pdf = slides_daemon.convert_with_google_drive_pull(
        pptx_path=tmp_path / "deck.pptx",
        output_pdf=out,
        config=cfg,
        state_entry=state_entry,
        drive_export_url="https://docs.google.com/presentation/d/abc/export/pdf",
        drive_probe_url="https://docs.google.com/presentation/d/abc/export/pdf",
    )
    assert pdf == out
    assert downloaded["called"] == 1
    assert state_entry["last_drive_fingerprint"].startswith("pdf:")
    assert state_entry["last_drive_fingerprint"] != "pdf:old"


def test_google_drive_pull_unchanged_fingerprint_alerts_when_drive_not_running(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.converter = "google_drive_pull"
    cfg.drive_sync_timeout_seconds = 10.0
    cfg.drive_poll_seconds = 5.0
    timeline = iter([1000.0, 1001.0, 1001.0, 1006.0, 1006.0, 1011.0, 1011.0])
    monkeypatch.setattr(slides_daemon.time, "time", lambda: next(timeline))
    monkeypatch.setattr(slides_daemon.time, "sleep", lambda _s: None)

    alerted = {}
    monkeypatch.setattr(slides_daemon, "_push_error_status", lambda _cfg, msg: alerted.setdefault("msg", msg))
    monkeypatch.setattr(slides_daemon, "_beep_local", lambda: alerted.setdefault("beep", True))
    monkeypatch.setattr(slides_daemon, "_is_google_drive_running", lambda: False)
    monkeypatch.setattr(
        slides_daemon,
        "_download_pdf_from_url",
        lambda _url, out: (out.parent.mkdir(parents=True, exist_ok=True), out.write_bytes(b"%PDF-1.4 SAME"), out)[2],
    )

    same_payload_fp = "pdf:" + slides_daemon.hashlib.sha256(b"%PDF-1.4 SAME").hexdigest()

    state_entry = {"last_drive_fingerprint": same_payload_fp}
    with pytest.raises(RuntimeError, match="drive_sync_timeout"):
        slides_daemon.convert_with_google_drive_pull(
            pptx_path=tmp_path / "deck.pptx",
            output_pdf=tmp_path / "work" / "deck.pdf",
            config=cfg,
            state_entry=state_entry,
            drive_export_url="https://docs.google.com/presentation/d/abc/export/pdf",
            drive_probe_url="https://docs.google.com/presentation/d/abc/export/pdf",
        )

    assert "Google Drive app not running" in alerted["msg"]
    assert alerted["beep"] is True
    assert state_entry["out_of_sync"] is True


def test_download_pdf_from_url_rejects_non_pdf(tmp_path, monkeypatch):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"not a pdf"

    monkeypatch.setattr(slides_daemon.urllib.request, "urlopen", lambda *args, **kwargs: _Resp())
    with pytest.raises(RuntimeError, match="invalid_pdf_payload"):
        slides_daemon._download_pdf_from_url("https://example.com/a.pdf", tmp_path / "a.pdf")


def test_convert_pptx_to_pdf_google_drive_pull_requires_export_url(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.converter = "google_drive_pull"
    with pytest.raises(RuntimeError, match="Missing drive_export_url"):
        slides_daemon.convert_pptx_to_pdf(
            pptx_path=tmp_path / "deck.pptx",
            config=cfg,
            slug="slug",
            state_entry={},
            metadata={},
        )
