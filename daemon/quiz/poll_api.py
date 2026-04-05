"""
Helpers for posting quiz state to the workshop server via WebSocket.
Falls back to HTTP for read-only fetches (summary points).
"""

from typing import Optional

from daemon import log
from daemon.config import Config
from daemon.http import _get_json
from daemon.poll.state import poll_state
from daemon.scores import scores
from daemon.session_state import get_current_session_id
import daemon.ws_publish as _pub
from daemon.ws_publish import broadcast
from daemon.ws_messages import QuizStatusMsg


def post_poll(quiz: dict, config: Config) -> None:
    """Create poll from quiz data."""
    question = quiz["question"]
    if quiz.get("source"):
        question += f"\n\n(Source: {quiz['source']}, p. {quiz.get('page', 'N/A')})"

    # Convert string options to dict format expected by poll_state
    raw_options = quiz["options"]
    options = [
        {"id": f"opt{i}", "text": str(opt).strip()}
        for i, opt in enumerate(raw_options)
        if str(opt).strip()
    ]

    poll = poll_state.create_poll(
        question=question,
        options=options,
        multi=len(quiz.get("correct_indices", [])) > 1,
    )
    if _pub._ws_client and _pub._ws_client.connected:
        # TODO: no model yet — poll_created is not in ws_messages registry
        _pub._ws_client.send({"type": "broadcast", "event": {"type": "poll_created", "poll": poll}})
    else:
        log.error("daemon", "Cannot broadcast poll: WS not connected")


def open_poll(config: Config) -> None:
    """Open voting on current poll."""
    poll_state.open_poll(scores.snapshot_base)
    if _pub._ws_client and _pub._ws_client.connected:
        # TODO: no model yet — poll_opened is not in ws_messages registry
        _pub._ws_client.send({"type": "broadcast", "event": {"type": "poll_opened", "poll": poll_state.poll}})
    else:
        log.error("daemon", "Cannot broadcast poll open: WS not connected")


def post_status(status: str, message: str, config: Config,
                session_folder: Optional[str] = None,
                session_notes: Optional[str] = None,
                slides: Optional[list[dict]] = None) -> None:
    if session_folder is not None or session_notes is not None or slides is not None:
        # Extended payload not covered by QuizStatusMsg — keep raw send
        # TODO: no model yet — QuizStatusMsg doesn't support session_folder/session_notes/slides fields
        event: dict = {"type": "quiz_status", "status": status, "message": message}
        if session_folder is not None or session_notes is not None:
            event["session_folder"] = session_folder
            event["session_notes"] = session_notes
        if slides is not None:
            event["slides"] = slides
        try:
            if _pub._ws_client and _pub._ws_client.connected:
                _pub._ws_client.send({"type": "broadcast", "event": event})
            else:
                log.error("daemon", f"Could not post status: WS not connected")
        except Exception as e:
            log.error("daemon", f"Could not post status: {e}")
    else:
        try:
            broadcast(QuizStatusMsg(status=status, message=message))
        except Exception as e:
            log.error("daemon", f"Could not post status: {e}")


def fetch_quiz_history(config: Config) -> str:
    """Return accumulated closed polls as markdown."""
    return poll_state.quiz_md_content.strip()


def fetch_summary_points(config: Config) -> list[dict]:
    """Fetch existing summary key points from the server. Returns [] on failure."""
    try:
        sid = get_current_session_id()
        url = f"{config.server_url}/api/{sid}/summary" if sid else f"{config.server_url}/api/summary"
        data = _get_json(url)
        return data.get("points", [])
    except RuntimeError:
        return []
