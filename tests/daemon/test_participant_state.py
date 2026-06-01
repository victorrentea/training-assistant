"""Tests for ParticipantState engagement runtime fields."""

from daemon.participant.state import ParticipantState


def test_new_state_has_empty_engagement_maps():
    ps = ParticipantState()
    assert ps.engagement == {}
    assert ps.last_active_at == {}
    assert ps.last_view == {}


def test_sync_from_restore_reads_engagement():
    ps = ParticipantState()
    ps.sync_from_restore(
        {
            "participants": {
                "u1": {
                    "name": "Alice",
                    "engagement": {"notes": {"seconds": 12, "visits": 1, "clicks": 0}},
                }
            }
        }
    )
    assert ps.participant_names["u1"] == "Alice"
    assert ps.engagement["u1"]["notes"]["seconds"] == 12


def test_reset_clears_engagement_and_liveness():
    ps = ParticipantState()
    ps.engagement["u1"] = {"slides": {"seconds": 5, "visits": 1, "clicks": 1}}
    ps.last_active_at["u1"] = 123.0
    ps.last_view["u1"] = "slides"
    ps.reset()
    assert ps.engagement == {}
    assert ps.last_active_at == {}
    assert ps.last_view == {}


def test_snapshot_includes_engagement():
    ps = ParticipantState()
    ps.engagement["u1"] = {"slides": {"seconds": 5, "visits": 1, "clicks": 2}}
    snap = ps.snapshot()
    assert snap["engagement"] == {"u1": {"slides": {"seconds": 5, "visits": 1, "clicks": 2}}}
