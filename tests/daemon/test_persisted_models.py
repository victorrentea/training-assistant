"""Tests for persisted Pydantic models — engagement metrics."""

from daemon.persisted_models import PersistedParticipant, PersistedSessionState, ViewEngagement


def test_view_engagement_defaults_to_zero():
    ve = ViewEngagement()
    assert (ve.seconds, ve.visits, ve.clicks) == (0, 0, 0)


def test_persisted_participant_carries_engagement():
    p = PersistedParticipant.model_validate(
        {
            "name": "Alice",
            "engagement": {"slides": {"seconds": 30, "visits": 2, "clicks": 5}},
        }
    )
    assert p.engagement["slides"].seconds == 30
    assert p.engagement["slides"].visits == 2
    assert p.engagement["slides"].clicks == 5


def test_persisted_participant_engagement_json_round_trip():
    p = PersistedParticipant.model_validate(
        {"name": "Bob", "engagement": {"notes": {"seconds": 12, "visits": 1, "clicks": 0}}}
    )
    p2 = PersistedParticipant.model_validate(p.model_dump(mode="json"))
    assert p2.engagement["notes"].seconds == 12


def test_persisted_participant_defaults_empty_engagement():
    p = PersistedParticipant.model_validate({"name": "Carol"})
    assert p.engagement == {}


def test_normalizer_folds_flat_engagement_into_participants():
    state = PersistedSessionState.model_validate(
        {
            "session_id": "t",
            "participant_names": {"u1": "Alice"},
            "engagement": {"u1": {"slides": {"seconds": 30, "visits": 2, "clicks": 5}}},
        }
    )
    assert state.participants["u1"].engagement["slides"].seconds == 30


def test_nested_engagement_wins_over_flat_legacy_map():
    state = PersistedSessionState.model_validate(
        {
            "session_id": "t",
            "participants": {
                "u1": {"name": "Alice", "engagement": {"slides": {"seconds": 99, "visits": 9, "clicks": 9}}}
            },
            "engagement": {"u1": {"slides": {"seconds": 1, "visits": 1, "clicks": 1}}},
        }
    )
    assert state.participants["u1"].engagement["slides"].seconds == 99
