import asyncio
import logging
from state import state
from persistence.db import get_connection
from persistence.serializers import serialize_activity_state

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
SNAPSHOT_INTERVAL = 2  # seconds


async def _snapshot_loop():
    while True:
        await asyncio.sleep(SNAPSHOT_INTERVAL)
        try:
            write_snapshot()
        except Exception:
            logger.exception("Snapshot write failed")


def write_snapshot():
    """Synchronous write of persistent state to SQLite."""
    conn = get_connection()
    try:
        with conn:
            # Upsert participants
            conn.executemany(
                """INSERT INTO participants (uuid, name, avatar, universe)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(uuid) DO UPDATE SET
                     name=excluded.name, avatar=excluded.avatar, universe=excluded.universe""",
                [
                    (uuid, name, state.participant_avatars.get(uuid, ''),
                     state.participant_universes.get(uuid, ''))
                    for uuid, name in state.participant_names.items()
                    if not uuid.startswith("__")
                ]
            )

            # Upsert scores
            conn.executemany(
                """INSERT INTO scores (uuid, score) VALUES (?, ?)
                   ON CONFLICT(uuid) DO UPDATE SET score=excluded.score""",
                [
                    (uuid, score)
                    for uuid, score in state.scores.items()
                ]
            )

            # Upsert mode
            conn.execute(
                """INSERT INTO app_settings (key, value) VALUES ('mode', ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (state.mode,)
            )

            # Upsert activity state JSON blobs
            activity_data = serialize_activity_state(state)
            conn.executemany(
                """INSERT INTO activity_state (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                list(activity_data.items())
            )
    finally:
        conn.close()


def start_snapshot_task():
    global _task
    _task = asyncio.create_task(_snapshot_loop())
    logger.info("Persistence snapshot task started (interval=%ds)", SNAPSHOT_INTERVAL)


def stop_snapshot_task():
    global _task
    if _task:
        _task.cancel()
        _task = None
