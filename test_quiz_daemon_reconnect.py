from pathlib import Path
from types import SimpleNamespace

import quiz_daemon


class _NoopTimestampAppender:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    def tick(self):
        pass


def test_daemon_logs_disconnect_once_then_reconnect(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(quiz_daemon, "_kill_previous", lambda: None)
    monkeypatch.setattr(quiz_daemon, "TranscriptTimestampAppender", _NoopTimestampAppender)
    monkeypatch.setattr(quiz_daemon.signal, "signal", lambda *args, **kwargs: None)
    monkeypatch.setattr(quiz_daemon, "DAEMON_POLL_INTERVAL", 0)
    monkeypatch.setattr(quiz_daemon.time, "sleep", lambda *_: None)
    monkeypatch.setenv("MATERIALS_FOLDER", str(tmp_path / "missing-materials"))

    pid_file = tmp_path / "daemon.pid"
    monkeypatch.setattr(quiz_daemon, "_PID_FILE", pid_file)

    config = SimpleNamespace(
        server_url="http://example.test",
        host_username="host",
        host_password="pwd",
        minutes=30,
        folder=tmp_path,
    )
    monkeypatch.setattr(quiz_daemon, "config_from_env", lambda: config)

    calls = {"n": 0}

    def _fake_get_json(url, username, password):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Cannot reach server")
        if calls["n"] in (2, 3):
            return {"request": None, "preview": None}
        raise KeyboardInterrupt()

    monkeypatch.setattr(quiz_daemon, "_get_json", _fake_get_json)

    quiz_daemon.run()

    out = capsys.readouterr()
    assert out.err.count("Server unreachable:") == 1
    assert "Reconnected to server." in out.out

