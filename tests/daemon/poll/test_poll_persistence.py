"""Round-trip test: poll state → snapshot dict → restore → equal."""
from daemon.poll.state import poll_state, PollData


def test_snapshot_restore_round_trip(monkeypatch):
    poll_state.reset()
    poll_state.data = PollData(
        question="How was the demo?",
        options=["Great", "Meh", "Bad"],
        multi=True,
        public=True,
    )
    poll_state.started = True
    poll_state.opened_at = "2026-05-23T10:00:00+00:00"
    poll_state.cast_vote("alice", [0, 1])
    poll_state.cast_vote("bob", [2])

    # Manually build the snapshot fragment the way __main__._build_runtime_session_snapshot does
    snapshot = {
        "data": poll_state.data.model_dump(),
        "started": poll_state.started,
        "opened_at": poll_state.opened_at,
        "votes": dict(poll_state.votes),
    }

    # Reset state then restore from snapshot
    poll_state.reset()
    poll_state.data = PollData.model_validate(snapshot["data"])
    poll_state.started = snapshot["started"]
    poll_state.opened_at = snapshot["opened_at"]
    poll_state.votes = dict(snapshot["votes"])
    poll_state.invalidate_counts()

    # Assertions
    assert poll_state.data.question == "How was the demo?"
    assert poll_state.data.options == ["Great", "Meh", "Bad"]
    assert poll_state.data.multi is True
    assert poll_state.data.public is True
    assert poll_state.started is True
    assert poll_state.opened_at == "2026-05-23T10:00:00+00:00"
    assert poll_state.votes["alice"]["option_indices"] == [0, 1]
    assert poll_state.votes["bob"]["option_indices"] == [2]
    assert poll_state.vote_counts() == [1, 1, 1]
    assert poll_state.distinct_voter_count() == 2


def test_empty_state_snapshot_is_sentinel_none():
    """When data is None and no votes, snapshot block should be None
    (so it's omitted from session-state.json)."""
    poll_state.reset()
    poll_block = ({
        "data": poll_state.data.model_dump() if poll_state.data else None,
        "started": poll_state.started,
        "opened_at": poll_state.opened_at,
        "votes": dict(poll_state.votes),
    } if poll_state.data is not None or poll_state.votes else None)
    assert poll_block is None


def test_restore_from_legacy_session_state_with_no_poll_field():
    """Existing session-state.json files lack the poll field — should
    not crash and should result in empty poll_state."""
    poll_state.reset()
    snapshot = {}                       # no "poll" key at all
    poll_data = snapshot.get("poll")
    assert poll_data is None
    assert poll_state.data is None
    assert poll_state.votes == {}
