import json, tempfile
from pathlib import Path

def test_save_session_state_writes_json():
    """_save_session_state writes session_state.json to the session folder."""
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        snapshot = {
            "saved_at": "2026-03-25T10:00:00",
            "mode": "workshop",
            "participants": {"uuid-1": {"name": "Alice", "score": 100}},
        }
        from daemon.session_state import save_session_state as _save_session_state
        _save_session_state(folder, snapshot)
        written = json.loads((folder / "session_state.json").read_text())
        assert written["participants"]["uuid-1"]["name"] == "Alice"
        assert written["mode"] == "workshop"

def test_save_session_state_overwrites_existing():
    """_save_session_state overwrites existing session_state.json atomically."""
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        existing = folder / "session_state.json"
        existing.write_text(json.dumps({"mode": "old"}))
        from daemon.session_state import save_session_state as _save_session_state
        _save_session_state(folder, {"mode": "new"})
        assert json.loads(existing.read_text())["mode"] == "new"
