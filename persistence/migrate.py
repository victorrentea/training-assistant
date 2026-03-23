import logging
import re
from pathlib import Path

from persistence.db import get_connection

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def run_migrations() -> None:
    """Apply all pending SQL migrations from the migrations/ directory."""
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                filename TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

        applied = {
            row["version"]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }

        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        pattern = re.compile(r"^(\d{3,})_.*\.sql$")

        for path in migration_files:
            match = pattern.match(path.name)
            if not match:
                continue
            version = int(match.group(1))
            if version in applied:
                continue

            sql = path.read_text(encoding="utf-8")
            try:
                conn.execute("BEGIN")
                for statement in sql.split(";"):
                    # Strip leading comment lines so they don't mask real SQL
                    lines = statement.strip().splitlines()
                    lines = [l for l in lines if not l.strip().startswith("--")]
                    cleaned = "\n".join(lines).strip()
                    if cleaned:
                        conn.execute(statement.strip())
                conn.execute(
                    "INSERT INTO schema_migrations (version, filename) VALUES (?, ?)",
                    (version, path.name),
                )
                conn.commit()
                logger.info("Applied migration %s", path.name)
            except Exception:
                conn.rollback()
                logger.exception("Failed to apply migration %s", path.name)
                raise
    finally:
        conn.close()
