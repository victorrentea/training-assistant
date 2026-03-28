"""Session ID validation for participant-facing routes."""
from fastapi import HTTPException
from core.state import state


def require_valid_session(session_id: str) -> str:
    """FastAPI dependency: validates session_id matches the active session."""
    if not state.session_id or session_id.lower() != state.session_id:
        raise HTTPException(status_code=404, detail="Invalid or expired session")
    return session_id
