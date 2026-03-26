from pathlib import Path

import training_daemon
from quiz_core import Config


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
    monkeypatch.setattr(training_daemon, "_post_json", lambda *args, **kwargs: {"ok": True})

    config = Config(
        server_url="http://example.test",
        host_username="host",
        host_password="pwd",
        minutes=30,
        folder=tmp_path,
        api_key="x",
        model="dummy",
        dry_run=False,
        project_folder=None,
    )
    monkeypatch.setattr(training_daemon, "config_from_env", lambda: config)

    calls = {"quiz_request": 0}

    def _fake_get_json(url, username=None, password=None):
        if url.endswith("/api/status"):
            return {"backend_version": "test-version", "needs_restore": False}
        if url.endswith("/api/session/request"):
            return {"action": None}
        if url.endswith("/api/quiz-request"):
            calls["quiz_request"] += 1
            if calls["quiz_request"] == 1:
                raise RuntimeError("Cannot reach server")
            if calls["quiz_request"] == 2:
                return {"request": None, "preview": None}
            raise KeyboardInterrupt()
        return {}

    monkeypatch.setattr(training_daemon, "_get_json", _fake_get_json)

    training_daemon.run()

    out = capsys.readouterr()
    assert out.err.count("Server unreachable:") == 1
    assert "Reconnected to server." in out.out


def test_slides_ws_connect_uses_additional_headers_when_supported(monkeypatch):
    calls: list[dict] = []

    class _DummyConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_connect(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return _DummyConn()

    monkeypatch.setattr(training_daemon, "ws_connect", _fake_connect)
    conn = training_daemon.SlidesOnDemandWsRunner._connect("wss://example/ws/daemon", {"Authorization": "Basic abc"})
    assert isinstance(conn, _DummyConn)
    assert len(calls) == 1
    assert calls[0]["additional_headers"] == {"Authorization": "Basic abc"}


def test_slides_ws_connect_falls_back_to_extra_headers(monkeypatch):
    calls: list[dict] = []

    class _DummyConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_connect(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if "additional_headers" in kwargs:
            raise TypeError("connect() got an unexpected keyword argument 'additional_headers'")
        return _DummyConn()

    monkeypatch.setattr(training_daemon, "ws_connect", _fake_connect)
    conn = training_daemon.SlidesOnDemandWsRunner._connect("wss://example/ws/daemon", {"Authorization": "Basic abc"})
    assert isinstance(conn, _DummyConn)
    assert len(calls) == 2
    assert calls[1]["extra_headers"] == {"Authorization": "Basic abc"}
