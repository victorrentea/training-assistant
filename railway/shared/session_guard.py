"""Session ID validation for participant-facing routes."""
from fastapi import HTTPException, Request

from railway.shared.session_registry import session_registry
from railway.shared.state import state


class InvalidSessionRedirect(Exception):
    """Raised for browser page requests with invalid session — triggers redirect."""
    pass


def is_active_session_id(session_id: str) -> bool:
    """True iff this id names the CURRENTLY-LIVE session (case-insensitive).

    The single source of truth for "is this path id the active session" — used by
    both guards below, the page handlers (live SPA vs read-only ended view) and
    the session-scoped status endpoint, so the anti-hijack matching can never
    drift between routes."""
    return bool(state.session_id) and session_id.lower() == state.session_id.lower()


def require_valid_session(session_id: str, request: Request) -> str:
    """FastAPI dependency: validates session_id matches the active session or a recent past session.
    Redirects browser page requests to landing; returns JSON 404 for API calls."""
    if is_active_session_id(session_id):
        return session_id
    # Past session in registry
    if session_registry.is_valid(session_id):
        return session_id
    # Not valid
    if request.headers.get("upgrade", "").lower() == "websocket":
        raise HTTPException(status_code=403, detail="Invalid session")
    path_after = request.url.path.split(f"/{session_id}", 1)[-1]
    if not path_after.startswith("/api/") and not path_after.startswith("/ws/"):
        raise InvalidSessionRedirect(session_id)
    raise HTTPException(status_code=404, detail="Session not found")


def require_active_session(session_id: str) -> str:
    """FastAPI dependency: only allows access to the currently active session."""
    if not is_active_session_id(session_id):
        raise HTTPException(status_code=404, detail="Session not active")
    return session_id
