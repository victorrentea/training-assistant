"""In-memory registry of valid session IDs for read-only access to past sessions."""
from datetime import datetime, timedelta, timezone

REGISTRY_TTL_DAYS = 90  # 3 months


class SessionRegistry:
    """Keys are stored lowercased: session-id matching is case-insensitive
    everywhere else (see ``session_guard.is_active_session_id``), so the registry
    must agree — otherwise a case-variant re-announce of the same session would
    create a duplicate entry, and a case-variant past link would miss its entry.

    Concurrency: all WRITES happen on the event loop (daemon WS handlers); READS
    also come from FastAPI's threadpool (the sync guard dependencies), so readers
    must use single atomic dict lookups — never a membership test followed by a
    separate access (``expire_old`` may delete the entry in between).
    """

    def __init__(self):
        self._entries: dict[str, dict] = {}  # session_id -> {folder_name, session_type, created_at, ended_at}

    def register(self, session_id: str, folder_name: str, session_type: str = "workshop"):
        """Record a session as active.

        Idempotent across daemon reconnects: when the same session is re-announced
        we PRESERVE the original ``created_at`` (so the TTL window measures from
        the first time we saw the session, not the latest reconnect) and simply
        clear ``ended_at`` — the session is live again. Prunes expired entries so
        the map stays bounded.
        """
        self.expire_old()
        key = session_id.lower()
        existing = self._entries.get(key)
        created_at = (existing or {}).get("created_at") or datetime.now(timezone.utc).isoformat()
        self._entries[key] = {
            "folder_name": folder_name,
            "session_type": session_type,
            "created_at": created_at,
            "ended_at": None,
        }

    def mark_ended(self, session_id: str):
        entry = self._entries.get(session_id.lower())
        if entry is not None:
            entry["ended_at"] = datetime.now(timezone.utc).isoformat()

    def is_valid(self, session_id: str) -> bool:
        """True if this session_id is active or a recent past session."""
        entry = self._entries.get(session_id.lower())  # single read — see class docstring
        if entry is None:
            return False
        created_at = datetime.fromisoformat(entry["created_at"])
        return datetime.now(timezone.utc) - created_at < timedelta(days=REGISTRY_TTL_DAYS)

    def get(self, session_id: str) -> dict | None:
        return self._entries.get(session_id.lower())

    def expire_old(self):
        cutoff = datetime.now(timezone.utc) - timedelta(days=REGISTRY_TTL_DAYS)
        to_remove = [sid for sid, e in self._entries.items()
                     if datetime.fromisoformat(e["created_at"]) < cutoff]
        for sid in to_remove:
            del self._entries[sid]


session_registry = SessionRegistry()
