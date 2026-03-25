import json, tempfile
from pathlib import Path


def test_load_daemon_state_new_format():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "daemon_state.json"
        f.write_text(json.dumps({
            "main": {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00", "status": "active"},
            "talk": None
        }))
        from training_daemon import _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result["main"]["name"] == "2026-03-25 WS"
        assert result["talk"] is None


def test_load_daemon_state_migrates_old_stack_format():
    """Old {stack:[...]} format is migrated to {main, talk}."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "daemon_state.json"
        f.write_text(json.dumps({
            "stack": [
                {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00"}
            ]
        }))
        from training_daemon import _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result["main"]["name"] == "2026-03-25 WS"
        assert result["talk"] is None


def test_load_daemon_state_migrates_two_item_stack():
    """Old stack with 2 items: first=main, second=talk."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "daemon_state.json"
        f.write_text(json.dumps({
            "stack": [
                {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00"},
                {"name": "2026-03-25 12:30 talk", "started_at": "2026-03-25T12:30:00"}
            ]
        }))
        from training_daemon import _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result["main"]["name"] == "2026-03-25 WS"
        assert result["talk"]["name"] == "2026-03-25 12:30 talk"


def test_load_daemon_state_returns_empty_when_no_file():
    with tempfile.TemporaryDirectory() as d:
        from training_daemon import _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result == {"main": None, "talk": None}


def test_save_daemon_state_writes_new_format():
    with tempfile.TemporaryDirectory() as d:
        from training_daemon import _save_daemon_state
        _save_daemon_state(Path(d), {
            "main": {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00", "status": "active"},
            "talk": None
        })
        data = json.loads((Path(d) / "daemon_state.json").read_text())
        assert "main" in data
        assert "stack" not in data
        assert data["main"]["name"] == "2026-03-25 WS"
