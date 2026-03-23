import os
import sqlite3
import logging

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "data/state.db"


def get_db_path() -> str:
    return os.environ.get("DB_PATH", DEFAULT_DB_PATH)


def get_connection() -> sqlite3.Connection:
    """Get a synchronous SQLite connection with WAL mode and Row factory."""
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn
