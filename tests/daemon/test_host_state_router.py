

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
