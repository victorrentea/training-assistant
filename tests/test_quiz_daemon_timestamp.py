from pathlib import Path
from types import SimpleNamespace

import training_daemon
from training_daemon import TranscriptTimestampAppender


def test_timestamp_appender_logs_missing_transcript_once(tmp_path: Path, capsys):
    appender = TranscriptTimestampAppender(folder=tmp_path, interval_seconds=3)

    appender.start()
    appender.tick()
    appender.tick()

    out = capsys.readouterr()
    assert "no .txt" in out.err
    assert out.err.count("no .txt") == 1


def test_timestamp_appender_appends_on_interval(tmp_path: Path):
    transcript = tmp_path / "session.txt"
    transcript.write_text("[ 00:00:22.50 ] Victor:\tHello", encoding="utf-8")

    appender = TranscriptTimestampAppender(folder=tmp_path, interval_seconds=0.01)
    appender.start()

    assert appender.enabled is True

    appender.tick()
    first = transcript.read_text(encoding="utf-8")
    assert "\n[ " in first
    assert "Victor" not in first.splitlines()[-1]

    appender.tick()
    second = transcript.read_text(encoding="utf-8")
    assert second == first


def test_slides_polling_runner_disables_cleanly_on_missing_config(monkeypatch):
    def _raise_config():
        raise RuntimeError("missing slides config")

    monkeypatch.setattr(training_daemon.slides_daemon, "config_from_env", _raise_config)
    runner = training_daemon.SlidesPollingRunner(
        SimpleNamespace(server_url="http://server", host_username="host", host_password="pwd")
    )
    runner.start()
    assert runner.enabled is False


def test_slides_polling_runner_uses_main_daemon_auth_and_server(tmp_path: Path, monkeypatch):
    cfg = SimpleNamespace(
        poll_interval_seconds=5.0,
        state_file=tmp_path / "slides-state.json",
        server_url="http://other-server",
        host_username="other-user",
        host_password="other-pass",
    )
    monkeypatch.setattr(training_daemon.slides_daemon, "config_from_env", lambda: cfg)
    monkeypatch.setattr(training_daemon.slides_daemon, "load_daemon_state", lambda _path: {"files": {}})
    seen = {}

    def _fake_run_once(run_cfg, _state):
        seen["server_url"] = run_cfg.server_url
        seen["host_username"] = run_cfg.host_username
        seen["host_password"] = run_cfg.host_password

    monkeypatch.setattr(training_daemon.slides_daemon, "run_once", _fake_run_once)

    runner = training_daemon.SlidesPollingRunner(
        SimpleNamespace(server_url="http://main-server", host_username="main-user", host_password="main-pass")
    )
    runner.start()
    runner.tick()

    assert runner.enabled is True
    assert seen == {
        "server_url": "http://main-server",
        "host_username": "main-user",
        "host_password": "main-pass",
    }


def test_materials_mirror_runner_detects_create_update_delete(tmp_path: Path, monkeypatch):
    materials = tmp_path / "materials"
    materials.mkdir()
    sample = materials / "slides" / "deck.pdf"
    sample.parent.mkdir(parents=True)
    sample.write_bytes(b"v1")

    monkeypatch.setenv("MATERIALS_FOLDER", str(materials))
    monkeypatch.setenv("MATERIALS_MIRROR_ENABLED", "1")
    monkeypatch.setenv("MATERIALS_MIRROR_INTERVAL_SECONDS", "1")
    monkeypatch.setenv("MATERIALS_MIRROR_STATE_FILE", str(tmp_path / "mirror-state.json"))

    uploaded = []
    deleted = []

    runner = training_daemon.MaterialsMirrorRunner(
        SimpleNamespace(server_url="http://main-server", host_username="main-user", host_password="main-pass")
    )
    monkeypatch.setattr(
        runner,
        "_post_material_upsert",
        lambda relative_path, file_path, source_mtime=None: uploaded.append((relative_path, file_path.read_bytes())),
    )
    monkeypatch.setattr(runner, "_post_material_delete", lambda relative_path: deleted.append(relative_path))

    runner.start()
    runner.tick()
    assert uploaded == [("slides/deck.pdf", b"v1")]
    assert deleted == []

    sample.write_bytes(b"v2")
    runner._next_run_at = 0
    runner.tick()
    assert uploaded[-1] == ("slides/deck.pdf", b"v2")

    sample.unlink()
    runner._next_run_at = 0
    runner.tick()
    assert deleted == ["slides/deck.pdf"]
