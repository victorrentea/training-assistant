# features/ws/daemon_protocol.py
"""Daemon WebSocket protocol — message types and push helpers."""
import logging
from core.state import state

logger = logging.getLogger(__name__)

# --- Inbound message types (daemon → backend) ---
MSG_SLIDES_CATALOG = "slides_catalog"
MSG_SLIDE_INVALIDATED = "slide_invalidated"
MSG_DAEMON_PING = "daemon_ping"
MSG_QUIZ_PREVIEW = "quiz_preview"
MSG_QUIZ_STATUS = "quiz_status"
MSG_POLL_CREATE = "poll_create"
MSG_POLL_OPEN = "poll_open"
MSG_DEBATE_AI_RESULT = "debate_ai_result"
MSG_SESSION_SYNC = "session_sync"
MSG_TRANSCRIPT_STATUS = "transcript_status"
MSG_TOKEN_USAGE = "token_usage"
MSG_NOTES_CONTENT = "notes_content"
MSG_SLIDES_CURRENT = "slides_current"
MSG_SLIDES_CLEAR = "slides_clear"
MSG_TRANSCRIPTION_LANGUAGE_STATUS = "transcription_language_status"
MSG_TIMING_EVENT = "timing_event"
MSG_STATE_RESTORE = "state_restore"
MSG_STATE_SNAPSHOT_RESULT = "state_snapshot_result"
MSG_SESSION_SNAPSHOT_RESULT = "session_snapshot_result"
MSG_ACTIVITY_LOG = "activity_log"
MSG_SESSION_FOLDERS = "session_folders"
MSG_GLOBAL_STATE_SAVED = "global_state_saved"

# --- Outbound message types (backend → daemon) ---
MSG_QUIZ_REQUEST = "quiz_request"
MSG_QUIZ_REFINE = "quiz_refine"
MSG_DEBATE_AI_REQUEST = "debate_ai_request"
MSG_SUMMARY_FORCE = "summary_force"
MSG_SUMMARY_FULL_RESET = "summary_full_reset"
MSG_SESSION_REQUEST = "session_request"
MSG_TRANSCRIPTION_LANGUAGE_REQUEST = "transcription_language_request"
MSG_STATE_SNAPSHOT_REQUEST = "state_snapshot_request"
MSG_SESSION_SNAPSHOT_REQUEST = "session_snapshot_request"
MSG_STATUS = "status"
MSG_SLIDE_LOG = "slide_log"
MSG_KICKED = "kicked"

# --- Static file sync (backend → daemon) ---
MSG_SYNC_FILES = "sync_files"

# --- Static file sync (daemon → backend) ---
MSG_RELOAD = "reload"

# --- Proxy (bidirectional) ---
MSG_PROXY_REQUEST = "proxy_request"
MSG_PROXY_RESPONSE = "proxy_response"

# --- Identity events (daemon → backend) ---
MSG_PARTICIPANT_REGISTERED = "participant_registered"
MSG_PARTICIPANT_LOCATION = "participant_location"
MSG_PARTICIPANT_AVATAR_UPDATED = "participant_avatar_updated"

# --- Generic broadcast (daemon → all participants via backend) ---
MSG_BROADCAST = "broadcast"

# --- Word cloud state sync (daemon → backend) ---
MSG_WORDCLOUD_STATE_SYNC = "wordcloud_state_sync"

# --- Score award (daemon → backend, transitional) ---
MSG_SCORE_AWARD = "score_award"

# --- State push (backend → daemon, on connect) ---
MSG_DAEMON_STATE_PUSH = "daemon_state_push"


async def push_to_daemon(msg: dict) -> bool:
    """Send a JSON message to the daemon via WebSocket. Returns True if sent."""
    ws = state.daemon_ws
    if ws is None:
        return False
    try:
        await ws.send_json(msg)
        return True
    except Exception:
        logger.warning("Failed to push to daemon: %s", msg.get("type", "unknown"))
        return False
