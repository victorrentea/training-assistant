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
        state_file.write_text(json.dumps({"session_id": "abc123", "participants": {"p1": {"name": "Alice"}}}))
        from daemon.session_state import save_session_state as _save_session_state
        _save_session_state(folder, {"session_id": None, "participants": {"p1": {"name": "Bob"}}})
        written = json.loads(state_file.read_text())
        assert written["session_id"] == "abc123"
        assert written["participants"]["p1"]["name"] == "Bob"


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


def test_load_session_state_normalizes_null_poll_correct_ids():
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        (folder / "session-state.json").write_text(
            json.dumps({
                "mode": "workshop",
                "poll_correct_ids": None,
            }),
            encoding="utf-8",
        )
        from daemon.session_state import load_session_state as _load_session_state
        loaded = _load_session_state(folder)
        assert loaded["poll_correct_ids"] == []


def test_load_session_state_normalizes_legacy_participant_maps():
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        (folder / "session-state.json").write_text(
            json.dumps({
                "participant_names": {"u1": "Gandalf"},
                "participant_avatars": {"u1": "gandalf.png"},
                "scores": {"u1": 0},
                "locations": {"u1": "🕐 America/Mexico_City"},
            }),
            encoding="utf-8",
        )
        from daemon.session_state import load_session_state as _load_session_state
        loaded = _load_session_state(folder)
        assert loaded["participants"]["u1"]["name"] == "Gandalf"
        assert loaded["participants"]["u1"]["avatar"] == "gandalf.png"
        assert loaded["participants"]["u1"]["score"] == 0
        assert loaded["participants"]["u1"]["location"] == "🕐 America/Mexico_City"


def test_save_session_state_logs_compact_write_line(capsys):
    with tempfile.TemporaryDirectory() as d:
        from daemon.session_state import save_session_state as _save_session_state

        folder = Path(d) / "2026-04-07..09 AI@Globex"
        folder.mkdir(parents=True, exist_ok=True)
        _save_session_state(folder, {"mode": "new"})
        out = capsys.readouterr().out
        assert "💾 session-state.json in 2026-04-07..09 AI@Globex" in out
