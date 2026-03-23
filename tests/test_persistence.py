import os
import sqlite3

import pytest

from state import state, ActivityType
from persistence.db import get_connection
from persistence.migrate import run_migrations
from persistence.snapshot import write_snapshot
from persistence.restore import restore_state


class TestPersistence:

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path, monkeypatch):
        """Point DB_PATH to a temp file and reset state before each test."""
        db_file = str(tmp_path / "test_state.db")
        monkeypatch.setenv("DB_PATH", db_file)
        state.reset()
        yield
        state.reset()

    def test_migrations_build_from_scratch(self, tmp_path):
        run_migrations()

        conn = get_connection()
        try:
            # Verify all expected tables exist
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            for expected in ("participants", "scores", "app_settings", "activity_state", "schema_migrations"):
                assert expected in tables, f"Table {expected} not found"

            # Verify default mode
            row = conn.execute("SELECT value FROM app_settings WHERE key='mode'").fetchone()
            assert row["value"] == "workshop"

            # Verify schema_migrations has 2 rows (001 + 002)
            count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            assert count == 2
        finally:
            conn.close()

    def test_migrations_idempotent(self):
        run_migrations()
        run_migrations()  # should not raise

        conn = get_connection()
        try:
            count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            assert count == 2
        finally:
            conn.close()

    def test_snapshot_and_restore_roundtrip(self):
        run_migrations()

        # Populate state
        state.participant_names["uuid-1"] = "Alice"
        state.participant_names["uuid-2"] = "Bob"
        state.participant_avatars["uuid-1"] = "gandalf.png"
        state.participant_universes["uuid-1"] = "LOTR"
        state.scores["uuid-1"] = 42
        state.scores["uuid-2"] = 17
        state.mode = "conference"

        write_snapshot()

        # Reset and restore
        state.reset()
        assert state.participant_names == {}
        assert state.scores == {}
        assert state.mode == "workshop"

        restore_state()

        assert state.participant_names["uuid-1"] == "Alice"
        assert state.participant_names["uuid-2"] == "Bob"
        assert state.participant_avatars["uuid-1"] == "gandalf.png"
        assert state.participant_universes["uuid-1"] == "LOTR"
        assert state.scores["uuid-1"] == 42
        assert state.scores["uuid-2"] == 17
        assert state.mode == "conference"

    def test_activity_state_roundtrip(self):
        run_migrations()

        # Poll with votes
        state.poll = {
            "id": "poll-1",
            "question": "Favorite color?",
            "multi": False,
            "correct_count": 1,
            "options": [{"id": "a", "text": "Red"}, {"id": "b", "text": "Blue"}],
        }
        state.poll_active = True
        state.votes = {"uuid-1": "a", "uuid-2": "b"}
        state.poll_correct_ids = ["a"]

        # Q&A with upvoter sets
        state.qa_questions = {
            "q1": {
                "id": "q1",
                "text": "What is Python?",
                "author": "uuid-1",
                "upvoters": {"uuid-2", "uuid-3"},
                "answered": False,
                "timestamp": 1234567890.0,
            }
        }

        # Code review with selections (set of ints) and confirmed lines (set)
        state.codereview_snippet = "print('hello')\nprint('world')"
        state.codereview_language = "python"
        state.codereview_phase = "reviewing"
        state.codereview_selections = {
            "uuid-1": {1, 2},
            "uuid-2": {2, 3},
        }
        state.codereview_confirmed = {2}

        # Debate with arguments containing upvoter sets and auto_assigned set
        state.debate_statement = "Python is the best language"
        state.debate_phase = "arguments"
        state.debate_sides = {"uuid-1": "for", "uuid-2": "against"}
        state.debate_arguments = [
            {
                "id": "arg-1",
                "author_uuid": "uuid-1",
                "side": "for",
                "text": "Easy to learn",
                "upvoters": {"uuid-2"},
                "ai_generated": False,
                "merged_into": None,
            }
        ]
        state.debate_auto_assigned = {"uuid-3", "uuid-4"}
        state.debate_champions = {"for": "uuid-1"}
        state.debate_first_side = "for"
        state.debate_round_index = 1
        state.debate_round_timer_seconds = 60

        # Need participant_names for snapshot to write anything
        state.participant_names["uuid-1"] = "Alice"

        write_snapshot()

        # Reset and restore
        state.reset()
        restore_state()

        # Poll
        assert state.poll["id"] == "poll-1"
        assert state.poll_active is True
        assert state.votes == {"uuid-1": "a", "uuid-2": "b"}
        assert state.poll_correct_ids == ["a"]

        # Q&A - sets restored as sets
        q1 = state.qa_questions["q1"]
        assert isinstance(q1["upvoters"], set)
        assert q1["upvoters"] == {"uuid-2", "uuid-3"}
        assert q1["answered"] is False

        # Code review - sets restored as sets
        assert isinstance(state.codereview_selections["uuid-1"], set)
        assert state.codereview_selections["uuid-1"] == {1, 2}
        assert state.codereview_selections["uuid-2"] == {2, 3}
        assert isinstance(state.codereview_confirmed, set)
        assert state.codereview_confirmed == {2}
        assert state.codereview_phase == "reviewing"

        # Debate
        assert state.debate_statement == "Python is the best language"
        assert state.debate_phase == "arguments"
        assert state.debate_sides == {"uuid-1": "for", "uuid-2": "against"}
        assert isinstance(state.debate_auto_assigned, set)
        assert state.debate_auto_assigned == {"uuid-3", "uuid-4"}
        assert isinstance(state.debate_arguments[0]["upvoters"], set)
        assert state.debate_arguments[0]["upvoters"] == {"uuid-2"}
        assert state.debate_champions == {"for": "uuid-1"}
        assert state.debate_first_side == "for"
        assert state.debate_round_index == 1
        assert state.debate_round_timer_seconds == 60

    def test_snapshot_filters_host_and_overlay(self):
        run_migrations()

        state.participant_names["uuid-1"] = "Alice"
        state.participant_names["__host__"] = "Host"
        state.participant_names["__overlay__"] = "Overlay"
        state.scores["uuid-1"] = 10

        write_snapshot()

        # Reset and restore
        state.reset()
        restore_state()

        assert "uuid-1" in state.participant_names
        assert "__host__" not in state.participant_names
        assert "__overlay__" not in state.participant_names
