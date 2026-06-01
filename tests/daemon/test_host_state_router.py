"""Tests that the host participant list surfaces engagement + liveness."""

from daemon.host_state_router import _build_host_participants_list
from daemon.participant.state import participant_state


def test_host_list_includes_engagement_and_liveness():
    participant_state.reset()
    try:
        participant_state.participant_names["u1"] = "Alice"
        participant_state.engagement["u1"] = {"slides": {"seconds": 30, "visits": 2, "clicks": 5}}
        participant_state.last_active_at["u1"] = 1700000000000.0
        participant_state.last_view["u1"] = "slides"
        rows = _build_host_participants_list()
        row = next(r for r in rows if r["uuid"] == "u1")
        assert row["engagement"] == {"slides": {"seconds": 30, "visits": 2, "clicks": 5}}
        assert row["last_active_at"] == 1700000000000.0
        assert row["last_view"] == "slides"
    finally:
        participant_state.reset()


def test_host_list_defaults_when_no_engagement():
    participant_state.reset()
    try:
        participant_state.participant_names["u9"] = "Bob"
        rows = _build_host_participants_list()
        row = next(r for r in rows if r["uuid"] == "u9")
        assert row["engagement"] == {}
        assert row["last_active_at"] == 0
        assert row["last_view"] == ""
    finally:
        participant_state.reset()


def test_build_slides_log_fields_reads_from_misc_state(monkeypatch):
    from daemon.misc.state import misc_state
    misc_state.slides_viewed = [
        {"slug": "ai-coding", "page": 3, "seconds": 120},
        {"slug": "ai-coding", "page": 4, "seconds": 30},
    ]
    misc_state.current_slide = None
    from daemon.host_state_router import _build_slides_log_fields
    fields = _build_slides_log_fields()
    assert fields["slides_log_deep_count"] == 2
    assert fields["slides_log_topic"] == "ai-coding"
    # Cleanup
    misc_state.slides_viewed = []
