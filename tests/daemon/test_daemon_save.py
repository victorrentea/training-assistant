import json, tempfile
from pathlib import Path

def test_save_session_state_writes_json():
    """_save_session_state writes session-state.json to the session folder."""
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        snapshot = {
            "saved_at": "2026-03-25T10:00:00",
            "mode": "workshop",
            "participants": {"uuid-1": {"name": "Alice", "score": 100}},
        }
        from daemon.session_state import save_session_state as _save_session_state
        _save_session_state(folder, snapshot)
        written = json.loads((folder / "session-state.json").read_text())
        assert written["participants"]["uuid-1"]["name"] == "Alice"
        assert written["mode"] == "workshop"

def test_save_session_state_overwrites_existing():
    """_save_session_state overwrites existing session-state.json atomically."""
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        existing = folder / "session-state.json"
        existing.write_text(json.dumps({"mode": "old"}))
        from daemon.session_state import save_session_state as _save_session_state
        _save_session_state(folder, {"mode": "new"})
        assert json.loads(existing.read_text())["mode"] == "new"


def test_load_session_state_returns_empty_when_missing():
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        from daemon.session_state import load_session_state as _load_session_state
        assert _load_session_state(folder) == {}


def test_load_session_state_returns_empty_when_invalid_json():
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        (folder / "session-state.json").write_text("{invalid", encoding="utf-8")
        from daemon.session_state import load_session_state as _load_session_state
        assert _load_session_state(folder) == {}


def test_save_session_state_logs_debug_when_enabled(capsys):
    with tempfile.TemporaryDirectory() as d:
        from daemon import log as daemon_log
        from daemon.session_state import save_session_state as _save_session_state

        previous_level = daemon_log.get_level()
        daemon_log.set_level("debug")
        try:
            _save_session_state(Path(d), {"mode": "new"})
            out = capsys.readouterr().out
            assert "debug" in out
            assert "Persisted session-state.json" in out
        finally:
            daemon_log.set_level(previous_level)
