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


def test_save_session_state_preserves_existing_session_id():
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        state_file = folder / "session-state.json"
        state_file.write_text(json.dumps({"session_id": "abc123", "participant_names": {"p1": "Alice"}}))
        from daemon.session_state import save_session_state as _save_session_state
        _save_session_state(folder, {"session_id": None, "participant_names": {"p1": "Bob"}})
        written = json.loads(state_file.read_text())
        assert written["session_id"] == "abc123"
        assert written["participant_names"]["p1"] == "Bob"


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


def test_save_session_state_logs_compact_write_line(capsys):
    with tempfile.TemporaryDirectory() as d:
        from daemon.session_state import save_session_state as _save_session_state

        folder = Path(d) / "2026-04-07..09 AI@Globex"
        folder.mkdir(parents=True, exist_ok=True)
        _save_session_state(folder, {"mode": "new"})
        out = capsys.readouterr().out
        assert "💾 session-state.json in 2026-04-07..09 AI@Globex" in out
