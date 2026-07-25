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


# ── Explicit anonymity signal (fixes #4 / #8) ─────────────────────────────────

def test_new_state_has_empty_anonymous_pids():
    assert ParticipantState().anonymous_pids == set()


def test_reset_clears_anonymous_pids():
    ps = ParticipantState()
    ps.anonymous_pids.add("u1")
    ps.reset()
    assert ps.anonymous_pids == set()


def test_anonymous_pids_round_trip_through_snapshot():
    ps = ParticipantState()
    ps.anonymous_pids.update({"u1", "u2"})
    snap = ps.snapshot()
    assert sorted(snap["anonymous_pids"]) == ["u1", "u2"]

    fresh = ParticipantState()
    fresh.sync_from_restore(snap)
    assert fresh.anonymous_pids == {"u1", "u2"}


def test_restore_without_signal_clears_on_wholesale_roster_replace():
    """A legacy snapshot (participants dict, no anonymous_pids key) leaves nobody
    tagged rather than guessing — prefer under-tagging over mis-tagging."""
    ps = ParticipantState()
    ps.anonymous_pids.add("stale")
    ps.sync_from_restore({"participants": {"u1": {"name": "Alice"}}})
    assert ps.anonymous_pids == set()
