import json
import tempfile
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


def test_load_session_state_normalizes_null_quiz_correct_indices():
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        (folder / "session-state.json").write_text(
            json.dumps({
                "mode": "workshop",
                "quiz_correct_indices": None,
            }),
            encoding="utf-8",
        )
        from daemon.session_state import load_session_state as _load_session_state
        loaded = _load_session_state(folder)
        assert loaded["quiz"]["correct_indices"] == []


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
    """The write line is just the floppy icon plus what changed — no filename, no session name."""
    with tempfile.TemporaryDirectory() as d:
        from daemon.session_state import save_session_state as _save_session_state

        folder = Path(d) / "2026-04-07..09 AI@Globex"
        folder.mkdir(parents=True, exist_ok=True)
        _save_session_state(folder, {"mode": "new"})
        out = capsys.readouterr().out
        assert "💾 mode" in out
        assert "session-state.json" not in out
        assert "AI@Globex" not in out


def test_save_session_state_logs_participant_subfield_change(capsys):
    """When only a participant sub-field (e.g. score) changes, the log must name that sub-field."""
    with tempfile.TemporaryDirectory() as d:
        from daemon.session_state import save_session_state as _save_session_state

        folder = Path(d) / "session"
        folder.mkdir(parents=True, exist_ok=True)
        _save_session_state(folder, {"participants": {"u1": {"name": "Alice", "score": 0}}})
        capsys.readouterr()  # discard initial-write line
        _save_session_state(folder, {"participants": {"u1": {"name": "Alice", "score": 5}}})
        out = capsys.readouterr().out
        assert "participants(score)" in out


def test_save_session_state_logs_participant_added_and_field(capsys):
    """Adding a participant and changing a field on another reports both signals."""
    with tempfile.TemporaryDirectory() as d:
        from daemon.session_state import save_session_state as _save_session_state

        folder = Path(d) / "session"
        folder.mkdir(parents=True, exist_ok=True)
        _save_session_state(folder, {"participants": {"u1": {"name": "Alice", "location": "Bucharest"}}})
        capsys.readouterr()
        _save_session_state(
            folder,
            {
                "participants": {
                    "u1": {"name": "Alice", "location": "Cluj"},
                    "u2": {"name": "Bob"},
                }
            },
        )
        out = capsys.readouterr().out
        assert "participants(+1, location)" in out


def test_save_session_state_translates_engagement_into_activity(capsys):
    """'engagement' is opaque — the log must say which part of the tool they were on."""
    with tempfile.TemporaryDirectory() as d:
        from daemon.session_state import save_session_state as _save_session_state

        folder = Path(d) / "session"
        folder.mkdir(parents=True, exist_ok=True)
        _save_session_state(folder, {"participants": {"u1": {"name": "Alice"}}})
        capsys.readouterr()
        _save_session_state(
            folder,
            {"participants": {"u1": {"name": "Alice", "engagement": {"notes": {"seconds": 30, "visits": 1, "clicks": 2}}}}},
        )
        out = capsys.readouterr().out
        assert "participants(viewed notes)" in out
        assert "engagement" not in out


def test_save_session_state_names_the_slide_participants_are_watching(capsys):
    """Participants follow the host's deck, so slide engagement is logged as 'deck:page'."""
    with tempfile.TemporaryDirectory() as d:
        from daemon.session_state import save_session_state as _save_session_state

        folder = Path(d) / "session"
        folder.mkdir(parents=True, exist_ok=True)
        _save_session_state(folder, {"participants": {"u1": {"name": "Alice"}}, "current_slide": {"slug": "spring", "page": 12}})
        capsys.readouterr()
        _save_session_state(
            folder,
            {
                "participants": {"u1": {"name": "Alice", "engagement": {"slides": {"seconds": 30, "visits": 1, "clicks": 2}}}},
                "current_slide": {"slug": "spring", "page": 12},
            },
        )
        out = capsys.readouterr().out
        assert "participants(viewed slides spring:12)" in out


def test_save_session_state_logs_current_slide_and_viewed_pages(capsys):
    """current_slide and slides_viewed changes name the deck and page, not just the key."""
    with tempfile.TemporaryDirectory() as d:
        from daemon.session_state import save_session_state as _save_session_state

        folder = Path(d) / "session"
        folder.mkdir(parents=True, exist_ok=True)
        _save_session_state(folder, {"current_slide": {"slug": "spring", "page": 3}})
        capsys.readouterr()
        _save_session_state(
            folder,
            {
                "current_slide": {"slug": "spring", "page": 4},
                "slides_viewed": [{"slug": "spring", "page": 4, "seconds": 12}],
            },
        )
        out = capsys.readouterr().out
        assert "current_slide(spring:4)" in out
        assert "slides_viewed(spring:4)" in out


def test_save_session_state_engagement_falls_back_to_unknown(capsys):
    """An unrecognised view slug degrades to 'unknown' rather than leaking the raw key."""
    with tempfile.TemporaryDirectory() as d:
        from daemon.session_state import save_session_state as _save_session_state

        folder = Path(d) / "session"
        folder.mkdir(parents=True, exist_ok=True)
        _save_session_state(folder, {"participants": {"u1": {"name": "Alice"}}})
        capsys.readouterr()
        _save_session_state(
            folder,
            {"participants": {"u1": {"name": "Alice", "engagement": {"holodeck": {"seconds": 5}}}}},
        )
        out = capsys.readouterr().out
        assert "participants(viewed unknown)" in out
