"""In-memory registry of valid session IDs for read-only access to past sessions."""
from datetime import datetime, timedelta, timezone

REGISTRY_TTL_DAYS = 90  # 3 months


class SessionRegistry:
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
        existing = self._entries.get(session_id)
        created_at = (existing or {}).get("created_at") or datetime.now(timezone.utc).isoformat()
        self._entries[session_id] = {
            "folder_name": folder_name,
            "session_type": session_type,
            "created_at": created_at,
            "ended_at": None,
        }

    def mark_ended(self, session_id: str):
        if session_id in self._entries:
            self._entries[session_id]["ended_at"] = datetime.now(timezone.utc).isoformat()

    def is_valid(self, session_id: str) -> bool:
        """True if this session_id is active or a recent past session."""
        if session_id not in self._entries:
            return False
        entry = self._entries[session_id]
        created_at = datetime.fromisoformat(entry["created_at"])
        return datetime.now(timezone.utc) - created_at < timedelta(days=REGISTRY_TTL_DAYS)

    def get(self, session_id: str) -> dict | None:
        return self._entries.get(session_id)

    def expire_old(self):
        cutoff = datetime.now(timezone.utc) - timedelta(days=REGISTRY_TTL_DAYS)
        to_remove = [sid for sid, e in self._entries.items()
                     if datetime.fromisoformat(e["created_at"]) < cutoff]
        for sid in to_remove:
            del self._entries[sid]


session_registry = SessionRegistry()
