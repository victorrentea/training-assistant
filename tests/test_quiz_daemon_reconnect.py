from pathlib import Path
from types import SimpleNamespace

import training_daemon


class _NoopTimestampAppender:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    def tick(self):
        pass


def test_daemon_logs_disconnect_once_then_reconnect(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(training_daemon, "_check_and_acquire_lock", lambda: None)
    monkeypatch.setattr(training_daemon, "_write_lock", lambda: None)
    monkeypatch.setattr(training_daemon, "TranscriptTimestampAppender", _NoopTimestampAppender)
    monkeypatch.setattr(training_daemon.signal, "signal", lambda *args, **kwargs: None)
    monkeypatch.setattr(training_daemon, "DAEMON_POLL_INTERVAL", 0)
    monkeypatch.setattr(training_daemon.time, "sleep", lambda *_: None)
    monkeypatch.setenv("MATERIALS_FOLDER", str(tmp_path / "missing-materials"))

    lock_file = tmp_path / "daemon.lock"
    monkeypatch.setattr(training_daemon, "_LOCK_FILE", lock_file)

    config = SimpleNamespace(
        server_url="http://example.test",
        host_username="host",
        host_password="pwd",
        minutes=30,
        folder=tmp_path,
    )
    monkeypatch.setattr(training_daemon, "config_from_env", lambda: config)

    calls = {"n": 0}

    def _fake_get_json(url, username, password):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Cannot reach server")
        if calls["n"] in (2, 3):
            return {"request": None, "preview": None}
        raise KeyboardInterrupt()

    monkeypatch.setattr(training_daemon, "_get_json", _fake_get_json)

    training_daemon.run()

    out = capsys.readouterr()
    assert out.err.count("Server unreachable:") == 1
    assert "Reconnected to server." in out.out

