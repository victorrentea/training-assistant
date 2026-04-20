from daemon import host_state_router


def test_build_slides_log_fields_reads_from_misc_state(monkeypatch):
    from daemon.misc.state import misc_state
    misc_state.slides_viewed = [
        {"file_name": "AI.pptx", "page": 3, "seconds": 120},
        {"file_name": "AI.pptx", "page": 4, "seconds": 30},
    ]
    misc_state.current_slide = None
    from daemon.host_state_router import _build_slides_log_entries, _build_slides_log_fields
    fields = _build_slides_log_fields()
    entries = _build_slides_log_entries()
    assert fields["slides_log_deep_count"] == 2
    assert len(entries) == 2
    assert entries[0]["file"] == "AI.pptx"
    assert entries[0]["seconds_spent"] == 120
    # Cleanup
    misc_state.slides_viewed = []
