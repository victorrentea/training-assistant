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
        assert loaded["poll"]["correct_ids"] == []


def test_load_session_state_normalizes_legacy_flat_activity_fields():
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        (folder / "session-state.json").write_text(
            json.dumps({
                "wordcloud_words": {"python": 2},
                "wordcloud_word_order": ["python"],
                "wordcloud_topic": "Languages",
                "codereview_snippet": "print('hi')",
                "codereview_language": "python",
                "codereview_phase": "selecting",
                "codereview_selections": {"u1": [1, 2]},
                "codereview_confirmed": [2],
                "debate_statement": "Tabs vs spaces",
                "debate_phase": "arguments",
                "debate_sides": {"u1": "for"},
                "debate_arguments": [{"id": "a1", "upvoters": []}],
                "debate_champions": {"for": "u1"},
                "debate_auto_assigned": ["u1"],
                "debate_first_side": "for",
                "debate_round_index": 1,
                "debate_round_timer_seconds": 30,
                "debate_round_timer_started_at": "2026-04-09T00:00:00+00:00",
            }),
            encoding="utf-8",
        )
        from daemon.session_state import load_session_state as _load_session_state
        loaded = _load_session_state(folder)
        assert loaded["wordcloud"]["words"] == {"python": 2}
        assert loaded["wordcloud"]["word_order"] == ["python"]
        assert loaded["wordcloud"]["topic"] == "Languages"
        assert loaded["codereview"]["snippet"] == "print('hi')"
        assert loaded["codereview"]["language"] == "python"
        assert loaded["codereview"]["phase"] == "selecting"
        assert loaded["codereview"]["selections"] == {"u1": [1, 2]}
        assert loaded["codereview"]["confirmed"] == [2]
        assert loaded["debate"]["statement"] == "Tabs vs spaces"
        assert loaded["debate"]["phase"] == "arguments"
        assert loaded["debate"]["sides"] == {"u1": "for"}
        assert loaded["debate"]["arguments"] == [{"id": "a1", "upvoters": []}]
        assert loaded["debate"]["champions"] == {"for": "u1"}
        assert loaded["debate"]["auto_assigned"] == ["u1"]
        assert loaded["debate"]["first_side"] == "for"
        assert loaded["debate"]["round_index"] == 1
        assert loaded["debate"]["round_timer_seconds"] == 30
        assert loaded["debate"]["round_timer_started_at"] == "2026-04-09T00:00:00+00:00"


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


def test_load_session_state_drops_non_persisted_transient_fields():
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        (folder / "session-state.json").write_text(
            json.dumps({
                "mode": "workshop",
                "summary_points": [{"text": "Old summary"}],
                "leaderboard_active": True,
            }),
            encoding="utf-8",
        )
        from daemon.session_state import load_session_state as _load_session_state
        loaded = _load_session_state(folder)
        assert "summary_points" not in loaded
        assert "leaderboard_active" not in loaded


def test_save_session_state_logs_compact_write_line(capsys):
    with tempfile.TemporaryDirectory() as d:
        from daemon.session_state import save_session_state as _save_session_state

        folder = Path(d) / "2026-04-07..09 AI@Globex"
        folder.mkdir(parents=True, exist_ok=True)
        _save_session_state(folder, {"mode": "new"})
        out = capsys.readouterr().out
        assert "💾 session-state.json in 2026-04-07..09 AI@Globex" in out
