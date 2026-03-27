import json
import os
from pathlib import Path

import pytest
import daemon.slides.daemon as slides_daemon
import daemon.slides.catalog as _slides_catalog
import daemon.slides.upload as _slides_upload
import daemon.slides.convert as _slides_convert
import daemon.slides.drive_sync as _slides_drive_sync


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
        converter="google_drive_pull",
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

    slug1 = _slides_catalog.ensure_slug(state, path)
    slug2 = _slides_catalog.ensure_slug(state, path)

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
    changed = _slides_catalog.detect_changed_files([a, b], state)
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
    changed = _slides_catalog.detect_changed_files([a], state, metadata=metadata, publish_dir=publish)
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
    changed = _slides_catalog.detect_changed_files([a], state, metadata=metadata, publish_dir=publish)
    assert changed == []

    marker.write_text("1500.0\n", encoding="utf-8")
    changed = _slides_catalog.detect_changed_files([a], state, metadata=metadata, publish_dir=publish)
    assert changed == [a]


def test_process_one_file_google_drive_pull(tmp_path, monkeypatch):
    watch = tmp_path / "watch"
    watch.mkdir()
    deck = watch / "deck.pptx"
    deck.write_bytes(b"x")

    cfg = _cfg(tmp_path)
    cfg.converter = "google_drive_pull"
    cfg.sync_backend = False
    state = {"files": {}}
    out_pdf = tmp_path / "work" / "deck.pdf"
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    out_pdf.write_bytes(b"%PDF")

    monkeypatch.setattr(_slides_upload, "convert_pptx_to_pdf", lambda *args, **kwargs: out_pdf)
    monkeypatch.setattr(_slides_upload, "upload_pdf", lambda *args, **kwargs: str(cfg.publish_dir / "Deck.pdf"))

    processed = _slides_upload.process_one_file(
        cfg,
        state,
        deck,
        metadata={"drive_export_url": "https://docs.google.com/presentation/d/abc/export/pdf"},
    )
    assert processed is True


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

    monkeypatch.setattr(_slides_upload, "convert_pptx_to_pdf", lambda *args, **kwargs: out_pdf)
    monkeypatch.setattr(
        _slides_upload,
        "upload_pdf",
        lambda *args, **kwargs: "https://slides.example.com/published.pdf",
    )

    pushed = {}

    def _fake_push(config, public_url, slug, source_file):
        pushed["url"] = public_url
        pushed["slug"] = slug
        pushed["source_file"] = source_file

    monkeypatch.setattr(_slides_upload, "push_current_slides", _fake_push)

    saved = {}

    def _fake_save(path, data):
        saved["path"] = path
        saved["data"] = data

    monkeypatch.setattr(_slides_upload, "save_daemon_state", _fake_save)

    processed = _slides_upload.process_one_file(cfg, state, deck)

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

    monkeypatch.setattr(_slides_upload, "convert_pptx_to_pdf", lambda *args, **kwargs: out_pdf)
    monkeypatch.setattr(_slides_upload, "upload_pdf", lambda *args, **kwargs: str(cfg.publish_dir / "Deck.pdf"))

    processed = _slides_upload.process_one_file(cfg, state, deck, target_pdf="Deck.pdf")
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

    monkeypatch.setattr(_slides_upload, "process_one_file", _fake_process)
    monkeypatch.setattr(_slides_upload, "sync_slides_list", lambda *_args, **_kwargs: False)
    changed = _slides_upload.run_once(cfg, state)
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

    monkeypatch.setattr(_slides_upload.time, "time", lambda: 103.0)
    monkeypatch.setattr(_slides_upload, "process_one_file", lambda *args, **kwargs: True)
    monkeypatch.setattr(_slides_upload, "sync_slides_list", lambda *_args, **_kwargs: False)

    changed = _slides_upload.run_once(cfg, state)
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
    files, metadata = _slides_catalog.resolve_tracked_sources(cfg)
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

    monkeypatch.setattr(_slides_upload, "process_one_file", _fake_process)
    monkeypatch.setattr(_slides_upload, "sync_slides_list", lambda *_args, **_kwargs: False)
    changed = _slides_upload.run_once(cfg, state)
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
        _slides_upload,
        "_post_json",
        lambda url, payload, *_args, **_kwargs: posted.append((url, payload)) or {"ok": True},
    )

    changed = _slides_upload.run_once(cfg, state)
    assert changed is True
    assert len(posted) == 1
    assert posted[0][0].endswith("/api/quiz-status")
    assert posted[0][1]["status"] == "ready"
    assert len(posted[0][1]["slides"]) == 1
    assert posted[0][1]["slides"][0]["name"] == "Intro"

    changed = _slides_upload.run_once(cfg, state)
    assert changed is False
    assert len(posted) == 1

    newer = intro.stat().st_mtime + 5.0
    os.utime(intro, (newer, newer))
    changed = _slides_upload.run_once(cfg, state)
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
        _slides_upload,
        "_post_json",
        lambda url, payload, *_args, **_kwargs: posted.append((url, payload)) or {"ok": True},
    )

    assert _slides_upload.run_once(cfg, state) is True
    assert len(posted[-1][1]["slides"]) == 2

    b.unlink()
    assert _slides_upload.run_once(cfg, state) is True
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


def test_config_rejects_non_google_drive_pull_converter(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"decks": []}), encoding="utf-8")
    monkeypatch.setenv("PPTX_CATALOG_FILE", str(catalog))
    monkeypatch.setenv("PPTX_CONVERTER", "libreoffice")
    monkeypatch.setenv("PPTX_SYNC_BACKEND", "0")
    with pytest.raises(RuntimeError, match="Only PPTX_CONVERTER=google_drive_pull is supported"):
        slides_daemon.config_from_env()


def test_extract_drive_export_links_from_html():
    html = """
    <html><body>
      <a href="https://docs.google.com/presentation/d/abc123/edit">AI Coding</a>
      <a href="https://docs.google.com/presentation/d/def456/preview">Reactive WebFlux</a>
      <a href="https://example.com/nope">Other</a>
    </body></html>
    """
    links = _slides_drive_sync.extract_drive_export_links(html)
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
    monkeypatch.setattr(_slides_upload, "_read_url_text", lambda *_args, **_kwargs: html)

    updated, missing = _slides_upload.bootstrap_drive_urls(catalog, "https://victorrentea.ro/slides/")
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
    monkeypatch.setattr(_slides_convert.time, "time", lambda: 1000.0)

    def _fake_download(_url, out):
        downloaded["called"] += 1
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"%PDF-1.4 NEW")
        return out

    monkeypatch.setattr(_slides_convert, "_download_pdf_from_url", _fake_download)

    out = tmp_path / "work" / "deck.pdf"
    state_entry = {"last_drive_fingerprint": "pdf:old"}
    pdf = _slides_convert.convert_with_google_drive_pull(
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
    monkeypatch.setattr(_slides_convert.time, "time", lambda: next(timeline))
    monkeypatch.setattr(_slides_convert.time, "sleep", lambda _s: None)

    alerted = {}
    monkeypatch.setattr(_slides_convert, "_push_error_status", lambda _cfg, msg: alerted.setdefault("msg", msg))
    monkeypatch.setattr(_slides_convert, "_beep_local", lambda: alerted.setdefault("beep", True))
    monkeypatch.setattr(_slides_convert, "_is_google_drive_running", lambda: False)
    monkeypatch.setattr(
        _slides_convert,
        "_download_pdf_from_url",
        lambda _url, out: (out.parent.mkdir(parents=True, exist_ok=True), out.write_bytes(b"%PDF-1.4 SAME"), out)[2],
    )

    same_payload_fp = "pdf:" + _slides_convert.hashlib.sha256(b"%PDF-1.4 SAME").hexdigest()

    state_entry = {"last_drive_fingerprint": same_payload_fp}
    with pytest.raises(RuntimeError, match="drive_sync_timeout"):
        _slides_convert.convert_with_google_drive_pull(
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

    monkeypatch.setattr(_slides_drive_sync.urllib.request, "urlopen", lambda *args, **kwargs: _Resp())
    with pytest.raises(RuntimeError, match="invalid_pdf_payload"):
        _slides_drive_sync._download_pdf_from_url("https://example.com/a.pdf", tmp_path / "a.pdf")


def test_convert_pptx_to_pdf_google_drive_pull_requires_export_url(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.converter = "google_drive_pull"
    with pytest.raises(RuntimeError, match="Missing drive_export_url"):
        _slides_convert.convert_pptx_to_pdf(
            pptx_path=tmp_path / "deck.pptx",
            config=cfg,
            slug="slug",
            state_entry={},
            metadata={},
        )


def test_log_startup_drive_sync_status_reports_pending_and_out_of_sync(tmp_path, monkeypatch):
    watch = tmp_path / "watch"
    watch.mkdir()
    deck = watch / "deck.pptx"
    deck.write_bytes(b"x")

    cfg = _cfg(tmp_path)
    cfg.watch_dir = watch
    cfg.catalog_file = None
    cfg.sync_backend = False

    state = {
        "files": {
            str(deck.resolve()): {
                "slug": "s1",
                "last_exported_mtime": deck.stat().st_mtime - 10.0,
                "out_of_sync": True,
            }
        }
    }

    logs: list[str] = []
    monkeypatch.setattr(_slides_upload.log, "info", lambda _name, msg: logs.append(msg))
    _slides_upload.log_startup_drive_sync_status(cfg, state)
    assert any("Startup pending Drive downloads (1):" in msg for msg in logs)
    assert any("Startup out-of-sync decks (1):" in msg for msg in logs)
