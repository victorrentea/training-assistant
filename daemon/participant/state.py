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
        self.debate_phase: str | None = None
        self.debate_sides: dict[str, str] = {}

    def sync_from_restore(self, data: dict):
        """Update cache from state_restore or session_sync data."""
        with self._lock:
            if "participant_names" in data:
                self.participant_names = dict(data["participant_names"])
            if "participant_avatars" in data:
                self.participant_avatars = dict(data["participant_avatars"])
            if "participant_universes" in data:
                self.participant_universes = dict(data["participant_universes"])
            if "scores" in data:
                self.scores = dict(data["scores"])
            if "locations" in data:
                self.locations = dict(data["locations"])
            if "mode" in data:
                self.mode = data["mode"]
            if "debate_phase" in data:
                self.debate_phase = data["debate_phase"]
            if "debate_sides" in data:
                self.debate_sides = dict(data["debate_sides"])

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
                "debate_phase": self.debate_phase,
                "debate_sides": dict(self.debate_sides),
            }


# Module-level singleton
participant_state = ParticipantState()
