import json
import tempfile
from pathlib import Path

from daemon.session_state import GLOBAL_STATE_FILENAME


def test_persisted_global_state_model_validates_new_shape():
    from daemon.persisted_models import PersistedGlobalState

    new_state = PersistedGlobalState.model_validate({
        "active_session_id": "abc123",
        "log_level": "debug",
    })
    assert new_state.active_session_id == "abc123"
    assert new_state.log_level == "debug"


def test_persisted_session_state_model_validates_runtime_snapshot_shape():
    from daemon.persisted_models import PersistedSessionState

    snapshot = PersistedSessionState.model_validate({
        "session_id": "session-1",
        "mode": "workshop",
        "current_activity": "qa",
        "participants": {
            "u1": {
                "name": "Alice",
                "avatar": "gandalf.png",
                "score": 100,
                "location": "🕐 America/Mexico_City",
            }
        },
        "qa_questions": {
            "q1": {
                "id": "q1",
                "text": "Question?",
                "author": "u1",
                "upvoters": ["u1"],
                "answered": False,
            }
        },
    })
    dumped = snapshot.model_dump()
    assert dumped["session_id"] == "session-1"
    assert dumped["participants"]["u1"]["name"] == "Alice"
    assert dumped["participants"]["u1"]["avatar"] == "gandalf.png"
    assert dumped["participants"]["u1"]["score"] == 100
    assert dumped["participants"]["u1"]["location"] == "🕐 America/Mexico_City"
    assert dumped["qa_questions"]["q1"]["text"] == "Question?"


def test_load_daemon_state_new_format():
    """New format stores only active_session_id."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / GLOBAL_STATE_FILENAME
        f.write_text(json.dumps({"active_session_id": "abc123"}))
        from daemon.session_state import load_daemon_state as _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result["active_session_id"] == "abc123"
        assert "main" not in result
        assert "talk" not in result



def test_load_daemon_state_returns_empty_when_no_file():
    with tempfile.TemporaryDirectory() as d:
        from daemon.session_state import load_daemon_state as _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result == {}


def test_load_daemon_state_returns_empty_for_non_object_root():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / GLOBAL_STATE_FILENAME
        f.write_text(json.dumps(["invalid-root"]), encoding="utf-8")
        from daemon.session_state import load_daemon_state as _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result == {}


def test_save_daemon_state_writes_active_session_id_only():
    """New format: only active_session_id is persisted to global state."""
    with tempfile.TemporaryDirectory() as d:
        from daemon.session_state import save_daemon_state as _save_daemon_state
        _save_daemon_state(Path(d), {"active_session_id": "abc123"})
        data = json.loads((Path(d) / GLOBAL_STATE_FILENAME).read_text())
        assert data == {"active_session_id": "abc123"}
        assert "main" not in data
        assert "stack" not in data


def test_load_daemon_state_reads_legacy_filename():
    with tempfile.TemporaryDirectory() as d:
        legacy = Path(d) / "daemon_state.json"
        legacy.write_text(json.dumps({"active_session_id": "legacy123"}))
        from daemon.session_state import load_daemon_state as _load_daemon_state
        result = _load_daemon_state(Path(d))
        assert result["active_session_id"] == "legacy123"


def test_load_daemon_state_renames_training_assistant_global_state():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        legacy = root / "training-assistant-global-state.json"
        legacy.write_text(json.dumps({"active_session_id": "legacy-global"}), encoding="utf-8")
        from daemon.session_state import load_daemon_state as _load_daemon_state
        result = _load_daemon_state(root)
        assert result["active_session_id"] == "legacy-global"
        assert (root / GLOBAL_STATE_FILENAME).exists()
        assert not legacy.exists()


# ── Session meta I/O ──────────────────────────────────────────────────────────

def test_save_and_load_session_meta():
    from daemon.session_state import load_session_meta, save_session_meta
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d) / "2026-03-25 WS"
        folder.mkdir()
        meta = {
            "session_id": "abc123",
            "started_at": "2026-03-25T09:00:00",
            "paused_intervals": [{"from": "2026-03-25T12:00:00", "to": "2026-03-25T13:00:00", "reason": "lunch"}],
        }
        save_session_meta(folder, meta)
        result = load_session_meta(folder)
        assert result["session_id"] == "abc123"
        assert "started_at" not in result
        assert "paused_intervals" not in result


def test_load_session_meta_returns_empty_when_no_file():
    from daemon.session_state import load_session_meta
    with tempfile.TemporaryDirectory() as d:
        result = load_session_meta(Path(d) / "missing-folder")
        assert result == {}


def test_find_session_folder_by_id_via_meta(tmp_path):
    from daemon.session_state import find_session_folder_by_id, save_session_meta
    folder = tmp_path / "2026-03-25 WS"
    folder.mkdir()
    save_session_meta(folder, {"session_id": "target-id-123", "started_at": "2026-03-25T09:00:00"})

    result = find_session_folder_by_id(tmp_path, "target-id-123")
    assert result == folder


def test_find_session_folder_by_id_via_session_state(tmp_path):
    from daemon.session_state import find_session_folder_by_id
    folder = tmp_path / "2026-03-25 WS"
    folder.mkdir()
    (folder / "session-state.json").write_text(json.dumps({"session_id": "server-id-456"}))

    result = find_session_folder_by_id(tmp_path, "server-id-456")
    assert result == folder


def test_find_session_folder_by_id_returns_none_when_not_found(tmp_path):
    from daemon.session_state import find_session_folder_by_id
    result = find_session_folder_by_id(tmp_path, "nonexistent-id")
    assert result is None


# ── announce_session_id ──────────────────────────────────────────────────────

def test_announce_session_id_sends_ws_message():
    """announce_session_id sends set_session_id WS message."""
    import daemon.session_state as session_state_mod

    captured = {}

    class FakeWsClient:
        connected = True
        def send(self, payload):
            captured["payload"] = payload

    original_ws = session_state_mod._ws_client
    session_state_mod._ws_client = FakeWsClient()
    try:
        from daemon.session_state import announce_session_id
        announce_session_id("abc123")
    finally:
        session_state_mod._ws_client = original_ws

    assert captured["payload"]["type"] == "set_session_id"
    assert captured["payload"]["session_id"] == "abc123"
    assert "session_name" not in captured["payload"]


def test_normalize_slides_manifest_accepts_slug_mapping():
    from daemon.session_state import _normalize_slides_manifest
    slides = _normalize_slides_manifest({
        "slides": {
            "arch-deck": {
                "url": "https://cdn.example.com/arch.pdf",
                "name": "Architecture Deck",
                "updated_at": "2026-03-25T11:00:00+00:00",
            }
        }
    })
    assert len(slides) == 1
    assert slides[0]["slug"] == "arch-deck"
    assert slides[0]["name"] == "Architecture Deck"
    assert slides[0]["url"] == "https://cdn.example.com/arch.pdf"


def test_load_slides_manifest_reads_candidate_file():
    from daemon.session_state import load_slides_manifest as _load_slides_manifest
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        (folder / "slides_manifest.json").write_text(json.dumps({
            "slides": [
                {"name": "Intro", "url": "https://cdn.example.com/intro.pdf"}
            ]
        }), encoding="utf-8")
        slides = _load_slides_manifest(folder)
        assert len(slides) == 1
        assert slides[0]["slug"] == "intro"
        assert slides[0]["url"] == "https://cdn.example.com/intro.pdf"


def test_resolve_session_folder_prefers_active_session_name(tmp_path):
    from daemon.__main__ import _resolve_session_folder_from_state

    sessions_root = tmp_path
    active_folder = sessions_root / "2026-03-29 Active"
    active_folder.mkdir()
    active_notes = active_folder / "active-notes.txt"
    active_notes.write_text("active")

    detected_folder = sessions_root / "2026-03-29 Abc"
    detected_folder.mkdir()
    detected_notes = detected_folder / "detected-notes.txt"
    detected_notes.write_text("detected")

    sf, sn, source = _resolve_session_folder_from_state(
        sessions_root=sessions_root,
        session_name=active_folder.name,
        detected_folder=detected_folder,
        detected_notes=detected_notes,
    )

    assert sf == active_folder
    assert sn == active_notes
    assert source == "stack"


def test_resolve_presentation_slide_target_uses_catalog_mapping(tmp_path):
    from daemon.__main__ import _resolve_presentation_slide_target

    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({
        "decks": [
            {
                "title": "About Victor",
                "source": "/Users/victorrentea/My Drive/Cursuri/Bio Victor.pptx",
                "target_pdf": "About Victor.pdf",
            }
        ]
    }), encoding="utf-8")

    target = _resolve_presentation_slide_target(
        presentation_name="Bio Victor.pptx",
        server_url="https://interact.victorrentea.ro",
        catalog_file=catalog,
    )
    assert target["slug"] == "about-victor"
    assert target["url"] == "https://interact.victorrentea.ro/api/slides/download/about-victor"
    assert target["matched"] is True


def test_resolve_presentation_slide_target_fallback_when_not_mapped(tmp_path):
    from daemon.__main__ import _resolve_presentation_slide_target

    target = _resolve_presentation_slide_target(
        presentation_name="Unmapped Deck.pptx",
        server_url="http://localhost:8000",
        catalog_file=tmp_path / "missing-catalog.json",
    )
    assert target["slug"] == "unmapped-deck"
    assert target["url"] == "http://localhost:8000/api/slides/download/unmapped-deck"
    assert target["matched"] is False


def test_session_state_hash_is_stable_for_key_order():
    from daemon.__main__ import _state_hash

    a = {"x": 1, "nested": {"b": 2, "a": 1}}
    b = {"nested": {"a": 1, "b": 2}, "x": 1}

    assert _state_hash(a) == _state_hash(b)


def test_without_session_id_strips_only_session_id():
    from daemon.__main__ import _without_session_id

    src = {"session_id": "abc123", "participants": {"p1": {"name": "Alice"}}}
    out = _without_session_id(src)
    assert out == {"participants": {"p1": {"name": "Alice"}}}
    assert src["session_id"] == "abc123"


def test_flush_session_state_backup_writes_when_hash_changed(tmp_path):
    from daemon.__main__ import _flush_session_state_backup

    sessions_root = tmp_path
    folder = sessions_root / "2026-03-25 WS"
    folder.mkdir()

    snapshot = {"participants": {"u1": {"name": "Alice"}}, "session_id": "sid-1"}
    last_hash, wrote = _flush_session_state_backup(
        sessions_root=sessions_root,
        session_name=folder.name,
        session_snapshot=snapshot,
        last_flushed_hash=None,
        force=False,
    )

    assert wrote is True
    assert isinstance(last_hash, str)
    assert json.loads((folder / "session-state.json").read_text(encoding="utf-8")) == snapshot


def test_flush_session_state_backup_skips_when_hash_unchanged(tmp_path):
    from daemon.__main__ import _flush_session_state_backup

    sessions_root = tmp_path
    folder = sessions_root / "2026-03-25 WS"
    folder.mkdir()
    snapshot = {"participants": {"u1": {"name": "Alice"}}, "session_id": "sid-1"}

    first_hash, first_wrote = _flush_session_state_backup(
        sessions_root=sessions_root,
        session_name=folder.name,
        session_snapshot=snapshot,
        last_flushed_hash=None,
        force=False,
    )
    assert first_wrote is True
    mtime_1 = (folder / "session-state.json").stat().st_mtime_ns

    second_hash, second_wrote = _flush_session_state_backup(
        sessions_root=sessions_root,
        session_name=folder.name,
        session_snapshot=snapshot,
        last_flushed_hash=first_hash,
        force=False,
    )
    mtime_2 = (folder / "session-state.json").stat().st_mtime_ns

    assert second_wrote is False
    assert second_hash == first_hash
    assert mtime_2 == mtime_1


def test_flush_session_state_backup_force_writes_even_when_hash_unchanged(tmp_path):
    from daemon.__main__ import _flush_session_state_backup

    sessions_root = tmp_path
    folder = sessions_root / "2026-03-25 WS"
    folder.mkdir()
    snapshot = {"participants": {"u1": {"name": "Alice"}}, "session_id": "sid-1"}

    first_hash, first_wrote = _flush_session_state_backup(
        sessions_root=sessions_root,
        session_name=folder.name,
        session_snapshot=snapshot,
        last_flushed_hash=None,
        force=False,
    )
    assert first_wrote is True

    second_hash, second_wrote = _flush_session_state_backup(
        sessions_root=sessions_root,
        session_name=folder.name,
        session_snapshot=snapshot,
        last_flushed_hash=first_hash,
        force=True,
    )

    assert second_wrote is True
    assert second_hash == first_hash


def test_flush_session_state_backup_skips_without_active_session(tmp_path):
    from daemon.__main__ import _flush_session_state_backup

    snapshot = {"participants": {"u1": {"name": "Alice"}}}
    out_hash, wrote = _flush_session_state_backup(
        sessions_root=tmp_path,
        session_name=None,
        session_snapshot=snapshot,
        last_flushed_hash=None,
        force=False,
    )

    assert wrote is False
    assert out_hash is None
    assert not (tmp_path / "session-state.json").exists()


def test_flush_global_state_backup_writes_when_hash_changed(tmp_path):
    from daemon.__main__ import _flush_global_state_backup
    from daemon.session_state import GLOBAL_STATE_FILENAME

    first_hash, first_wrote = _flush_global_state_backup(
        sessions_root=tmp_path,
        global_state={"active_session_id": "abc123", "log_level": "debug"},
        last_flushed_hash=None,
        force=False,
    )
    assert first_wrote is True
    assert isinstance(first_hash, str)
    assert (tmp_path / GLOBAL_STATE_FILENAME).exists()

    second_hash, second_wrote = _flush_global_state_backup(
        sessions_root=tmp_path,
        global_state={"active_session_id": "abc123", "log_level": "debug"},
        last_flushed_hash=first_hash,
        force=False,
    )
    assert second_wrote is False
    assert second_hash == first_hash


def test_ensure_session_state_file_for_resume_creates_missing_file(tmp_path):
    from daemon.__main__ import _ensure_session_state_file_for_resume

    folder = tmp_path / "resume-folder"
    folder.mkdir()
    wrote = _ensure_session_state_file_for_resume(
        session_folder=folder,
        session_snapshot={"participants": {"u1": {"name": "Alice"}}},
    )
    assert wrote is True
    assert (folder / "session-state.json").exists()


def test_ensure_session_state_file_for_resume_rewrites_empty_file(tmp_path):
    from daemon.__main__ import _ensure_session_state_file_for_resume

    folder = tmp_path / "resume-folder"
    folder.mkdir()
    (folder / "session-state.json").write_text("", encoding="utf-8")
    wrote = _ensure_session_state_file_for_resume(
        session_folder=folder,
        session_snapshot={"participants": {"u1": {"name": "Alice"}}},
    )
    assert wrote is True
    data = json.loads((folder / "session-state.json").read_text(encoding="utf-8"))
    assert data["participants"]["u1"]["name"] == "Alice"


def test_ensure_session_state_file_for_resume_keeps_existing_file(tmp_path):
    from daemon.__main__ import _ensure_session_state_file_for_resume

    folder = tmp_path / "resume-folder"
    folder.mkdir()
    state_file = folder / "session-state.json"
    state_file.write_text(json.dumps({"participants": {"u1": {"name": "Old"}}}), encoding="utf-8")
    wrote = _ensure_session_state_file_for_resume(
        session_folder=folder,
        session_snapshot={"participants": {"u1": {"name": "New"}}},
    )
    assert wrote is False
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["participants"]["u1"]["name"] == "Old"


def test_apply_snapshot_restore_updates_participant_names():
    from daemon.__main__ import _apply_runtime_snapshot_restore
    from daemon.participant.state import participant_state

    participant_state.reset()
    participant_state.participant_names["u-old"] = "ShouldBeCleared"
    participant_state.participant_avatars["u-old"] = "old.png"
    participant_state.scores["u-old"] = 5
    participant_state.locations["u-old"] = "Old"

    _apply_runtime_snapshot_restore({
        "participants": {
            "u1": {
                "name": "Persisted Tester",
                "avatar": "gandalf.png",
                "score": 100,
                "location": "🕐 America/Mexico_City",
            }
        },
        "mode": "workshop",
        "current_activity": "none",
    })

    assert participant_state.participant_names == {"u1": "Persisted Tester"}
    assert participant_state.participant_avatars == {"u1": "gandalf.png"}
    assert participant_state.scores == {"u1": 100}
    assert participant_state.locations == {"u1": "🕐 America/Mexico_City"}


def test_apply_snapshot_restore_ignores_participant_universes():
    from daemon.__main__ import _apply_runtime_snapshot_restore
    from daemon.participant.state import participant_state

    participant_state.reset()

    _apply_runtime_snapshot_restore({
        "participant_universes": {"u1": "Star Wars"},
    })

    assert participant_state.participant_universes == {}


def test_runtime_session_snapshot_excludes_participant_universes():
    from daemon.__main__ import _build_runtime_session_snapshot
    from daemon.codereview.state import codereview_state
    from daemon.debate.state import debate_state
    from daemon.participant.state import participant_state
    from daemon.poll.state import poll_state
    from daemon.scores import scores as daemon_scores
    from daemon.wordcloud.state import wordcloud_state
    participant_state.reset()
    daemon_scores.reset()
    poll_state.clear()
    wordcloud_state.clear()
    codereview_state.clear()
    debate_state.reset()

    participant_state.participant_names["u1"] = "Alice"
    participant_state.participant_avatars["u1"] = "gandalf.png"
    participant_state.scores["u1"] = 0
    daemon_scores.scores["u1"] = 0
    participant_state.locations["u1"] = "🕐 America/Mexico_City"
    participant_state.participant_universes["u1"] = "Star Wars"
    poll_state.poll = {"id": "p1", "question": "Q", "options": [], "multi": False}
    poll_state.poll_active = True
    poll_state.poll_correct_indices = [0]
    poll_state.votes = {"u1": {"option_ids": ["a1"], "voted_at": "2026-04-09T00:00:00+00:00"}}
    wordcloud_state.words = {"python": 2}
    wordcloud_state.word_order = ["python"]
    wordcloud_state.topic = "Language"
    codereview_state.snippet = "print('x')"
    codereview_state.language = "python"
    codereview_state.phase = "selecting"
    codereview_state.selections = {"u1": {1}}
    codereview_state.confirmed = {1}
    debate_state.statement = "Tabs vs spaces"
    debate_state.phase = "arguments"
    debate_state.sides = {"u1": "for"}
    debate_state.arguments = [
        {
            "id": "a1",
            "author_uuid": "u1",
            "side": "for",
            "text": "Argument",
            "upvoters": set(),
            "ai_generated": False,
            "merged_into": None,
        }
    ]
    debate_state.champions = {"for": "u1"}
    debate_state.auto_assigned = {"u1"}
    debate_state.first_side = "for"
    debate_state.round_index = 0
    debate_state.round_timer_seconds = 45
    debate_state.round_timer_started_at = None

    snapshot = _build_runtime_session_snapshot(
        active_session_id="sid-1",
        session_name="2026-04-09 Demo Session",
    )

    assert "participant_universes" not in snapshot
    assert snapshot["participants"] == {
        "u1": {
            "name": "Alice",
            "avatar": "gandalf.png",
            "score": 0,
            "location": "🕐 America/Mexico_City",
        }
    }
    assert "poll_active" not in snapshot
    assert "wordcloud_words" not in snapshot
    assert "codereview_snippet" not in snapshot
    assert "debate_statement" not in snapshot
    assert snapshot["poll"]["active"] is True
    assert snapshot["poll"]["correct_indices"] == [0]
    assert snapshot["wordcloud"]["words"] == {"python": 2}
    assert snapshot["codereview"]["snippet"] == "print('x')"
    assert snapshot["debate"]["statement"] == "Tabs vs spaces"


def test_apply_snapshot_restore_accepts_nested_activity_state():
    from daemon.__main__ import _apply_runtime_snapshot_restore
    from daemon.codereview.state import codereview_state
    from daemon.debate.state import debate_state
    from daemon.wordcloud.state import wordcloud_state

    wordcloud_state.clear()
    codereview_state.clear()
    debate_state.reset()

    _apply_runtime_snapshot_restore({
        "wordcloud": {"words": {"python": 2}, "word_order": ["python"], "topic": "Lang"},
        "codereview": {
            "snippet": "print('ok')",
            "language": "python",
            "phase": "reviewing",
            "selections": {"u1": [0, 1]},
            "confirmed": [1],
        },
        "debate": {
            "statement": "Tabs vs spaces",
            "phase": "arguments",
            "sides": {"u1": "for"},
            "arguments": [
                {
                    "id": "a1",
                    "author_uuid": "u1",
                    "side": "for",
                    "text": "Argument",
                    "upvoters": [],
                    "ai_generated": False,
                    "merged_into": None,
                }
            ],
            "champions": {"for": "u1"},
            "auto_assigned": ["u1"],
            "first_side": "for",
            "round_index": 1,
            "round_timer_seconds": 30,
            "round_timer_started_at": "2026-04-09T00:00:00+00:00",
        },
    })

    assert wordcloud_state.words == {"python": 2}
    assert wordcloud_state.word_order == ["python"]
    assert wordcloud_state.topic == "Lang"
    assert codereview_state.snippet == "print('ok')"
    assert codereview_state.language == "python"
    assert codereview_state.phase == "reviewing"
    assert codereview_state.selections == {"u1": {0, 1}}
    assert codereview_state.confirmed == {1}
    assert debate_state.statement == "Tabs vs spaces"
    assert debate_state.phase == "arguments"
    assert debate_state.sides == {"u1": "for"}
    assert debate_state.arguments[0]["upvoters"] == set()
    assert debate_state.champions == {"for": "u1"}
    assert debate_state.auto_assigned == {"u1"}
    assert debate_state.first_side == "for"
    assert debate_state.round_index == 1
    assert debate_state.round_timer_seconds == 30
    assert debate_state.round_timer_started_at is not None


def test_runtime_snapshot_includes_awarded_points():
    """The snapshot writer must surface poll_state.awarded_points so it round-trips to disk."""
    from daemon.__main__ import _build_runtime_session_snapshot
    from daemon.poll.state import poll_state

    poll_state.clear()
    poll_state.create_poll("Q?", ["A", "B"])
    poll_state.open_poll(lambda: None)
    poll_state.awarded_points = {"alice": 750, "bob": 200}

    snap = _build_runtime_session_snapshot(active_session_id="sid-test", session_name="Test Session")

    assert "poll" in snap
    assert snap["poll"].get("awarded_points") == {"alice": 750, "bob": 200}

    poll_state.clear()
