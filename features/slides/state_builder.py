"""Slides state builder — contributes slides/session state to participant and host state messages."""
from core.state import state


def build_for_participant(pid: str) -> dict:
    return {
        "slides_current": state.slides_current,
        "slides_cache_status": state.slides_cache_status,
        "session_main": state.session_main,
        "session_talk": state.session_talk,
        "session_name": (state.session_talk or state.session_main or {}).get("name"),
    }


def build_for_host() -> dict:
    return {
        "slides_current": state.slides_current,
        "slides_cache_status": state.slides_cache_status,
        "session_main": state.session_main,
        "session_talk": state.session_talk,
        "session_name": (state.session_talk or state.session_main or {}).get("name"),
    }


from core.messaging import register_state_builder
register_state_builder("slides", build_for_participant, build_for_host)
