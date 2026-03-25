from pathlib import Path
from types import SimpleNamespace

import training_daemon


def test_daemon_logs_disconnect_once_then_reconnect(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(training_daemon, "_check_and_acquire_lock", lambda: None)
    monkeypatch.setattr(training_daemon, "_write_lock", lambda: None)
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
        project_folder=None,
    )
    monkeypatch.setattr(training_daemon, "config_from_env", lambda: config)
    monkeypatch.setattr(
        training_daemon,
        "dc_replace",
        lambda obj, **kwargs: SimpleNamespace(**({**vars(obj), **kwargs})),
    )
    monkeypatch.setattr(training_daemon, "_post_json", lambda *args, **kwargs: {})

    quiz_request_calls = {"n": 0}

    def _fake_get_json(url, *args, **kwargs):
        if url.endswith("/api/status"):
            return {"backend_version": "v1", "needs_restore": False}
        if url.endswith("/api/session/request"):
            return {"action": None}
        if url.endswith("/api/quiz-request"):
            quiz_request_calls["n"] += 1
            if quiz_request_calls["n"] == 1:
                raise RuntimeError("Cannot reach server")
            if quiz_request_calls["n"] == 2:
                return {
                    "request": None,
                    "needs_restore": False,
                    "session_folder": None,
                    "has_notes_content": True,
                    "has_key_points": True,
                }
            raise KeyboardInterrupt()
        return {}

    monkeypatch.setattr(training_daemon, "_get_json", _fake_get_json)

    training_daemon.run()

    out = capsys.readouterr()
    assert out.err.count("Server unreachable:") == 1
    assert "Reconnected to server." in out.out
