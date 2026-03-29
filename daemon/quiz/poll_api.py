"""
Helpers for posting quiz state to the workshop server via WebSocket.
Falls back to HTTP for read-only fetches (quiz history, summary points).
"""

from typing import Optional

from daemon import log
from daemon.config import Config
from daemon.http import _get_json
from daemon.session_state import get_current_session_id

# Module-level ws_client reference, set by daemon/__main__.py at startup
_ws_client = None


def set_ws_client(client) -> None:
    """Set the module-level ws_client reference."""
    global _ws_client
    _ws_client = client


def post_poll(quiz: dict, config: Config) -> None:
    payload = {
        "type": "poll_create",
        "question": quiz["question"],
        "options": quiz["options"],
        "multi": len(quiz.get("correct_indices", [])) > 1,
    }
    if quiz.get("source"):
        payload["question"] += f"\n\n(Source: {quiz['source']}, p. {quiz.get('page', 'N/A')})"

    if _ws_client and _ws_client.connected:
        _ws_client.send(payload)
    else:
        log.error("daemon", "Cannot post poll: WS not connected")


def open_poll(config: Config) -> None:
    if _ws_client and _ws_client.connected:
        _ws_client.send({"type": "poll_open"})
    else:
        log.error("daemon", "Cannot open poll: WS not connected")


def post_status(status: str, message: str, config: Config,
                session_folder: Optional[str] = None,
                session_notes: Optional[str] = None,
                slides: Optional[list[dict]] = None) -> None:
    payload: dict = {"type": "quiz_status", "status": status, "message": message}
    if session_folder is not None or session_notes is not None:
        payload["session_folder"] = session_folder
        payload["session_notes"] = session_notes
    if slides is not None:
        payload["slides"] = slides
    try:
        if _ws_client and _ws_client.connected:
            _ws_client.send(payload)
        else:
            log.error("daemon", f"Could not post status: WS not connected")
    except Exception as e:
        log.error("daemon", f"Could not post status: {e}")


def fetch_quiz_history(config: Config) -> str:
    """Fetch previously asked questions from the server as markdown. Returns '' on failure."""
    try:
        sid = get_current_session_id()
        url = f"{config.server_url}/api/{sid}/quiz-md" if sid else f"{config.server_url}/api/quiz-md"
        data = _get_json(url)
        return data.get("content", "").strip()
    except RuntimeError:
        return ""


def fetch_summary_points(config: Config) -> list[dict]:
    """Fetch existing summary key points from the server. Returns [] on failure."""
    try:
        sid = get_current_session_id()
        url = f"{config.server_url}/api/{sid}/summary" if sid else f"{config.server_url}/api/summary"
        data = _get_json(url)
        return data.get("points", [])
    except RuntimeError:
        return []
