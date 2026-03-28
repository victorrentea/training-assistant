from pathlib import Path
from unittest.mock import MagicMock

import daemon.__main__ as training_daemon
import daemon.lock as _daemon_lock
from daemon.config import Config


class _NoopTimestampAppender:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    def tick(self):
        pass


def test_daemon_logs_disconnect_once_then_reconnect(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(training_daemon, "check_and_acquire_lock", lambda: None)
    monkeypatch.setattr(training_daemon, "write_lock", lambda: None)
    monkeypatch.setattr(training_daemon, "TranscriptTimestampAppender", _NoopTimestampAppender)
    monkeypatch.setattr(_daemon_lock.signal, "signal", lambda *args, **kwargs: None)
    monkeypatch.setattr(training_daemon, "DAEMON_POLL_INTERVAL", 0)
    monkeypatch.setattr(training_daemon.time, "sleep", lambda *_: None)
    monkeypatch.setenv("MATERIALS_FOLDER", str(tmp_path / "missing-materials"))

    lock_file = tmp_path / "daemon.lock"
    monkeypatch.setattr(training_daemon, "_LOCK_FILE", lock_file)

    # Mock DaemonWsClient so no real WebSocket connection is attempted
    mock_ws = MagicMock()
    mock_ws.connected = True
    mock_ws.send = MagicMock(return_value=True)
    monkeypatch.setattr(training_daemon, "DaemonWsClient", lambda: mock_ws)

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

    calls = {"status": 0}

    def _fake_get_json(url, username=None, password=None):
        if url.endswith("/api/status"):
            calls["status"] += 1
            if calls["status"] == 1:
                # Startup version check — succeed
                return {"backend_version": "test-version", "needs_restore": False}
            if calls["status"] == 2:
                # Startup restore check — succeed
                return {"backend_version": "test-version", "needs_restore": False}
            if calls["status"] == 3:
                # First loop iteration — simulate disconnect
                raise RuntimeError("Cannot reach server")
            if calls["status"] == 4:
                # Second loop iteration — reconnect
                return {"backend_version": "test-version", "needs_restore": False}
            # Third loop iteration — stop the test
            raise KeyboardInterrupt()
        return {}

    monkeypatch.setattr(training_daemon, "_get_json", _fake_get_json)

    training_daemon.run()

    out = capsys.readouterr()
    assert out.err.count("Server unreachable") == 1
    assert "Reconnected to server." in out.out
