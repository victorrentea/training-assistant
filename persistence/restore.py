import logging
from state import state
from persistence.db import get_connection
from persistence.serializers import restore_activity_state

logger = logging.getLogger(__name__)

def restore_state():
    """Load persistent state from SQLite into the AppState singleton."""
    conn = get_connection()
    try:
        # Restore participants (name, avatar, universe)
        rows = conn.execute("SELECT uuid, name, avatar, universe FROM participants").fetchall()
        for row in rows:
            state.participant_names[row["uuid"]] = row["name"]
            if row["avatar"]:
                state.participant_avatars[row["uuid"]] = row["avatar"]
            if row["universe"]:
                state.participant_universes[row["uuid"]] = row["universe"]

        # Restore scores
        rows = conn.execute("SELECT uuid, score FROM scores").fetchall()
        for row in rows:
            state.scores[row["uuid"]] = row["score"]

        # Restore mode
        row = conn.execute("SELECT value FROM app_settings WHERE key='mode'").fetchone()
        if row:
            state.mode = row["value"]

        # Restore activity state from JSON blobs
        rows = conn.execute("SELECT key, value FROM activity_state").fetchall()
        activity_data = {row["key"]: row["value"] for row in rows}
        restore_activity_state(state, activity_data)

        logger.info(
            "Restored state: %d participants, %d scores, mode=%s, activity=%s",
            len(state.participant_names), len(state.scores), state.mode, state.current_activity.value
        )
    finally:
        conn.close()
