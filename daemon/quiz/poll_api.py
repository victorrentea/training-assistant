"""
HTTP helpers for posting quiz state to the workshop server.
"""

from typing import Optional

from daemon import log
from daemon.config import Config
from daemon.http import _get_json, _post_json, _put_json


def post_poll(quiz: dict, config: Config) -> None:
    payload = {
        "question": quiz["question"],
        "options": quiz["options"],
        "multi": len(quiz.get("correct_indices", [])) > 1,
    }
    if quiz.get("source"):
        payload["question"] += f"\n\n(Source: {quiz['source']}, p. {quiz.get('page', 'N/A')})"

    _post_json(f"{config.server_url}/api/poll", payload, config.host_username, config.host_password)


def open_poll(config: Config) -> None:
    _put_json(f"{config.server_url}/api/poll/status", {"open": True}, config.host_username, config.host_password)


def post_status(status: str, message: str, config: Config,
                session_folder: Optional[str] = None,
                session_notes: Optional[str] = None,
                slides: Optional[list[dict]] = None) -> None:
    payload: dict = {"status": status, "message": message}
    if session_folder is not None or session_notes is not None:
        payload["session_folder"] = session_folder
        payload["session_notes"] = session_notes
    if slides is not None:
        payload["slides"] = slides
    try:
        _post_json(f"{config.server_url}/api/quiz-status",
                   payload,
                   config.host_username, config.host_password)
    except RuntimeError as e:
        log.error("daemon", f"Could not post status: {e}")


def fetch_quiz_history(config: Config) -> str:
    """Fetch previously asked questions from the server as markdown. Returns '' on failure."""
    try:
        data = _get_json(f"{config.server_url}/api/quiz-md")
        return data.get("content", "").strip()
    except RuntimeError:
        return ""


def fetch_summary_points(config: Config) -> list[dict]:
    """Fetch existing summary key points from the server. Returns [] on failure."""
    try:
        data = _get_json(f"{config.server_url}/api/summary")
        return data.get("points", [])
    except RuntimeError:
        return []
