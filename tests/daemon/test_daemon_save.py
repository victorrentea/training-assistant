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
        assert "participants(Alice: score)" in out


def test_save_session_state_logs_participant_added_and_field(capsys):
    """Adding a participant and changing a field on another names both people."""
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
        assert "participants(+Bob; Alice: location)" in out


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
        assert "participants(Alice: viewed notes)" in out
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
        assert "participants(Alice: viewed slides spring:12)" in out


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
        assert "participants(Alice: viewed unknown)" in out


def test_save_session_state_caps_the_number_of_people_it_names(capsys):
    """A bulk change must not print a wall of names — past a handful it degrades to a count."""
    with tempfile.TemporaryDirectory() as d:
        from daemon.session_state import save_session_state as _save_session_state

        folder = Path(d) / "session"
        folder.mkdir(parents=True, exist_ok=True)
        names = ["Alice", "Bob", "Carol", "Dan", "Eve", "Frank"]
        _save_session_state(folder, {"participants": {n: {"name": n, "score": 0} for n in names}})
        capsys.readouterr()
        _save_session_state(folder, {"participants": {n: {"name": n, "score": 1} for n in names}})
        out = capsys.readouterr().out
        assert "Alice: score" in out
        assert "+2 more" in out
        assert "Frank" not in out


# ── Two-producer merge regression ───────────────────────────────────────────
#
# save_session_state() is called by two independent producers with disjoint
# top-level key sets:
#   - participant_state.persist() (daemon/participant/state.py::snapshot()):
#     roster/scores/locations, fx_*, attention_enabled, emoji_*, anonymous/
#     trainer pids.
#   - the daemon's periodic runtime-activity flush
#     (daemon/__main__.py::_build_runtime_session_snapshot()): quiz, poll,
#     debate, qa_questions, wordcloud, codereview, slide tracking.
# A whole-file replace made either call silently delete the other producer's
# most recent data. These fixtures mirror the real shapes (not toy dicts) so
# the tests exercise the actual disjoint key sets.

def _participant_state_snapshot(**overrides) -> dict:
    """Shape of daemon/participant/state.py::ParticipantState.snapshot()."""
    base = {
        "participant_names": {"u1": "Alice"},
        "participant_avatars": {"u1": "alice.png"},
        "online_participants": ["u1"],
        "scores": {"u1": 10},
        "locations": {"u1": "Bucharest"},
        "location_timezones": {"u1": "Europe/Bucharest"},
        "location_countries": {"u1": "RO"},
        "mode": "workshop",
        "current_activity": "none",
        "emoji_counters": {"🎉": 3},
        "emoji_global_enabled": True,
        "attention_enabled": True,
        "fx_enabled": True,
        "fx_token": "abc123def456",
        "fx_tile_n": 69,
        "fx_cooldown_seconds": 10,
        "fx_last_fired_at": 1000.0,
        "engagement": {"u1": {"notes": {"seconds": 30, "visits": 1, "clicks": 0}}},
        "anonymous_pids": [],
        "trainer_pids": ["u1"],
    }
    base.update(overrides)
    return base


def _runtime_session_snapshot(**overrides) -> dict:
    """Shape of daemon/__main__.py::_build_runtime_session_snapshot()."""
    base = {
        "session_name": "2026-09-16 Test",
        "mode": "workshop",
        "current_activity": "quiz",
        "participants": {"u1": {"name": "Alice", "score": 10}},
        "quiz": {
            "definition": {"question": "2+2?", "options": ["3", "4"]},
            "active": True,
            "correct_indices": [1],
            "opened_at": "2026-09-16T10:00:00",
            "timer_seconds": 30,
            "timer_started_at": "2026-09-16T10:00:00",
            "votes": {"u1": 1},
            "awarded_points": {"u1": 5},
        },
        "poll": None,
        "qa_questions": {
            "q1": {"id": "q1", "text": "Why?", "author": "u1", "upvoters": [], "answered": False},
        },
        "wordcloud": {"words": {"python": 2}, "word_order": ["python"], "topic": "Languages"},
        "codereview": {
            "snippet": "print(1)",
            "language": "python",
            "phase": "reviewing",
            "selections": {},
            "confirmed": [],
        },
        "debate": {
            "statement": "Tabs vs spaces",
            "phase": "arguments",
            "sides": {},
            "arguments": [],
            "champions": {},
            "auto_assigned": [],
            "first_side": None,
            "round_index": None,
            "round_timer_seconds": None,
            "round_timer_started_at": None,
        },
        "current_slide": {"slug": "spring", "page": 3},
        "slides_viewed": [{"slug": "spring", "page": 3, "seconds": 12}],
        "slide_timeline": [{"slug": "spring", "page": 3, "seconds": 12, "at": "2026-09-16T10:05:00"}],
        "talk_presentation_name": None,
        "talk_presentation_url": None,
        "talk_presentation_slug": None,
    }
    base.update(overrides)
    return base


def test_producer_a_and_producer_b_fields_coexist_across_alternating_writes():
    """Write A's shape, then B's, then A's again — both sets of keys must
    survive every write, with the latest value each producer wrote."""
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        from daemon.session_state import save_session_state as _save_session_state

        _save_session_state(folder, _participant_state_snapshot())
        written = json.loads((folder / "session-state.json").read_text())
        assert written["fx_token"] == "abc123def456"
        assert written["attention_enabled"] is True

        _save_session_state(folder, _runtime_session_snapshot())
        written = json.loads((folder / "session-state.json").read_text())
        # B's own fields landed...
        assert written["quiz"]["active"] is True
        assert written["qa_questions"]["q1"]["text"] == "Why?"
        assert written["debate"]["statement"] == "Tabs vs spaces"
        # ...and A's fields from the previous write were NOT clobbered.
        assert written["fx_token"] == "abc123def456"
        assert written["fx_enabled"] is True
        assert written["attention_enabled"] is True
        assert written["emoji_counters"] == {"🎉": 3}
        assert written["trainer_pids"] == ["u1"]

        _save_session_state(folder, _participant_state_snapshot(fx_token="newtoken1234", fx_enabled=False))
        written = json.loads((folder / "session-state.json").read_text())
        # A's updated fields landed...
        assert written["fx_token"] == "newtoken1234"
        assert written["fx_enabled"] is False
        # ...and B's activity state from the previous write is still intact.
        assert written["quiz"]["active"] is True
        assert written["qa_questions"]["q1"]["text"] == "Why?"
        assert written["wordcloud"]["words"] == {"python": 2}
        assert written["current_slide"] == {"slug": "spring", "page": 3}


def test_fx_fields_survive_a_subsequent_activity_flush():
    """The FX-specific regression: participant_state.persist() writes
    fx_token/fx_enabled, then the runtime flush (which knows nothing about
    FX) must not wipe them."""
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        from daemon.session_state import save_session_state as _save_session_state

        _save_session_state(folder, _participant_state_snapshot(fx_enabled=True, fx_token="secretlink1"))
        _save_session_state(folder, _runtime_session_snapshot())

        written = json.loads((folder / "session-state.json").read_text())
        assert written["fx_enabled"] is True
        assert written["fx_token"] == "secretlink1"


def test_quiz_and_qa_questions_survive_a_subsequent_participant_persist():
    """The data-loss regression: the runtime flush writes quiz/qa_questions,
    then a participant_state.persist() call (e.g. from the public FX fire
    endpoint) must not wipe the live activity state."""
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        from daemon.session_state import save_session_state as _save_session_state

        _save_session_state(folder, _runtime_session_snapshot())
        _save_session_state(folder, _participant_state_snapshot())

        written = json.loads((folder / "session-state.json").read_text())
        assert written["quiz"]["active"] is True
        assert written["quiz"]["definition"]["question"] == "2+2?"
        assert written["qa_questions"]["q1"]["text"] == "Why?"
        assert written["debate"]["statement"] == "Tabs vs spaces"


def test_fx_fields_round_trip_through_a_restart_via_the_real_state_objects():
    """Real round-trip through a restart: save via the actual ParticipantState
    object, let a runtime flush happen afterwards (as it would every 3s in
    production), then load via the normal restore path (load_session_state +
    sync_from_restore) and confirm the FX fields come back.

    Unlike TestRoundTrip in test_fx_state.py (which only exercises
    snapshot()/sync_from_restore() against in-memory dicts), this goes
    through the actual session-state.json file on disk — the file I/O path
    that the whole-file-replace bug lived in.
    """
    from daemon.participant.state import ParticipantState
    from daemon.session_state import load_session_state as _load_session_state
    from daemon.session_state import save_session_state as _save_session_state

    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)

        armed = ParticipantState()
        armed.fx_enabled = True
        armed.fx_token = "abc123def456"
        armed.fx_tile_n = 3
        armed.fx_cooldown_seconds = 30
        armed.fx_last_fired_at = 1789554996.0
        _save_session_state(folder, armed.snapshot())

        # A runtime-activity flush happens after the FX link was armed, exactly
        # as it does every ~3s in production.
        _save_session_state(folder, _runtime_session_snapshot())

        restored = ParticipantState()
        restored.sync_from_restore(_load_session_state(folder))

        assert restored.fx_enabled is True
        assert restored.fx_token == "abc123def456"
        assert restored.fx_tile_n == 3
        assert restored.fx_cooldown_seconds == 30
        assert restored.fx_last_fired_at == 1789554996.0


def test_fx_token_can_still_be_explicitly_cleared():
    """Deletion semantics: a merge can no longer clear a field by omitting it,
    but both real producers always write an explicit value for every field
    they own (an inactive quiz is still `{"active": False, ...}`, a cleared
    token is an explicit `fx_token: None`) — they never rely on omission.
    Confirm an explicit clear still takes effect through the merge."""
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        from daemon.session_state import save_session_state as _save_session_state

        _save_session_state(folder, _participant_state_snapshot(fx_token="abc123def456", fx_enabled=True))
        written = json.loads((folder / "session-state.json").read_text())
        assert written["fx_token"] == "abc123def456"

        # A fresh session reset: fx_token goes back to None, fx_enabled to False —
        # both explicit values, as ParticipantState.reset() produces via snapshot().
        _save_session_state(folder, _participant_state_snapshot(fx_token=None, fx_enabled=False))
        written = json.loads((folder / "session-state.json").read_text())
        assert written["fx_token"] is None
        assert written["fx_enabled"] is False


def test_legacy_flat_fields_do_not_leak_back_in_after_a_merge():
    """exclude_unset pitfall: a merged dict's keys are all "explicitly set",
    which could make a legacy/exclude=True field (e.g. quiz_active, promoted
    to the nested `quiz` shape) reappear in the output once it is folded into
    `existing` and re-validated. It must not — legacy fields stay gone once
    normalized, on every subsequent write."""
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        from daemon.session_state import save_session_state as _save_session_state

        _save_session_state(folder, {"quiz_active": True, "quiz_correct_indices": [1]})
        written = json.loads((folder / "session-state.json").read_text())
        assert "quiz_active" not in written
        assert "quiz_correct_indices" not in written
        assert written["quiz"]["active"] is True

        # A second, unrelated write must not resurrect the legacy flat keys.
        _save_session_state(folder, _participant_state_snapshot())
        written = json.loads((folder / "session-state.json").read_text())
        assert "quiz_active" not in written
        assert "quiz_correct_indices" not in written
        assert written["quiz"]["active"] is True


def test_save_session_state_log_line_reports_only_genuinely_changed_keys(capsys):
    """After the merge fix, the 💾 log line must not list every key in the
    file just because it merged unrelated producer data in — only keys whose
    value actually changed on this call."""
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        from daemon.session_state import save_session_state as _save_session_state

        _save_session_state(folder, _participant_state_snapshot())
        capsys.readouterr()  # discard the initial-write line

        _save_session_state(folder, _runtime_session_snapshot())
        out = capsys.readouterr().out
        # B's own keys changed (this is a first write of activity state)...
        assert "quiz" in out
        assert "qa_questions" in out
        # ...but A's untouched keys from the previous write must NOT be
        # reported as "changed" just because they were merged into the file.
        assert "fx_token" not in out
        assert "fx_enabled" not in out
        assert "attention_enabled" not in out
        assert "trainer_pids" not in out
