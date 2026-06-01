"""Tests for persisted Pydantic models — engagement metrics."""

from daemon.persisted_models import PersistedParticipant, ViewEngagement


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
