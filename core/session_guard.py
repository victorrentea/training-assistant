"""Session ID validation for participant-facing routes."""
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from core.state import state


class InvalidSessionRedirect(Exception):
    """Raised for browser page requests with invalid session — triggers redirect."""
    pass


def require_valid_session(session_id: str, request: Request) -> str:
    """FastAPI dependency: validates session_id matches the active session.
    Redirects browser page requests to landing; returns JSON 404 for API calls."""
    if not state.session_id or session_id.lower() != state.session_id:
        path_after = request.url.path.split(f"/{session_id}", 1)[-1]
        if not path_after.startswith("/api/") and not path_after.startswith("/ws/"):
            raise InvalidSessionRedirect()
        raise HTTPException(status_code=404, detail="Invalid or expired session")
    return session_id
