"""Local participant state cache for daemon identity logic.

This is a read-only cache of Railway's AppState participant fields,
updated locally when the daemon processes identity requests.
Initial data comes from session_sync/state_restore on WS connect.
"""
import threading


class ParticipantState:
    """Participant state cache for daemon identity logic.

    Thread safety: The router endpoints (async def) run on uvicorn's event loop
    (single-threaded), so concurrent proxy requests are serialized at await points.
    The _lock is only needed for sync_from_restore() which runs on the main thread
    while router handlers may be running on the uvicorn thread.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.participant_names: dict[str, str] = {}
        self.participant_avatars: dict[str, str] = {}
        self.participant_universes: dict[str, str] = {}
        self.scores: dict[str, int] = {}
        self.locations: dict[str, str] = {}
        self.mode: str = "workshop"
        self.current_activity: str = "none"

    def sync_from_restore(self, data: dict):
        """Update cache from state_restore or session_sync data.

        Uses in-place clear+update to preserve dict object identity so that
        router handlers holding a reference to the same dict object don't
        silently lose their writes.
        """
        with self._lock:
            if "participant_names" in data:
                self.participant_names.clear()
                self.participant_names.update(data["participant_names"])
            if "participant_avatars" in data:
                self.participant_avatars.clear()
                self.participant_avatars.update(data["participant_avatars"])
            if "participant_universes" in data:
                self.participant_universes.clear()
                self.participant_universes.update(data["participant_universes"])
            if "scores" in data:
                self.scores.clear()
                self.scores.update(data["scores"])
            if "locations" in data:
                self.locations.clear()
                self.locations.update(data["locations"])
            if "mode" in data:
                self.mode = data["mode"]
            if "current_activity" in data:
                self.current_activity = str(data["current_activity"])

    def snapshot(self) -> dict:
        """Return a copy of all state (for testing/debugging)."""
        with self._lock:
            return {
                "participant_names": dict(self.participant_names),
                "participant_avatars": dict(self.participant_avatars),
                "participant_universes": dict(self.participant_universes),
                "scores": dict(self.scores),
                "locations": dict(self.locations),
                "mode": self.mode,
                "current_activity": self.current_activity,
            }


# Module-level singleton
participant_state = ParticipantState()
