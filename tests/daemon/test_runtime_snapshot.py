"""Tests that the runtime snapshot builder persists participant engagement."""

from daemon.__main__ import _build_runtime_session_snapshot
from daemon.participant.state import participant_state


def test_snapshot_includes_participant_engagement():
    participant_state.reset()
    try:
        participant_state.participant_names["u1"] = "Alice"
        participant_state.engagement["u1"] = {
            "slides": {"seconds": 30, "visits": 2, "clicks": 5}
        }
        snap = _build_runtime_session_snapshot(session_name="test-session")
        assert snap["participants"]["u1"]["engagement"] == {
            "slides": {"seconds": 30, "visits": 2, "clicks": 5}
        }
    finally:
        participant_state.reset()


def test_snapshot_persists_engagement_only_participant():
    participant_state.reset()
    try:
        # A participant that reported engagement before being named must still persist.
        participant_state.engagement["u2"] = {"notes": {"seconds": 9, "visits": 1, "clicks": 0}}
        snap = _build_runtime_session_snapshot(session_name="test-session")
        assert snap["participants"]["u2"]["engagement"]["notes"]["seconds"] == 9
    finally:
        participant_state.reset()
