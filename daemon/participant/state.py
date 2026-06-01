"""Local participant state cache for daemon identity logic.

This is a read-only cache of Railway's AppState participant fields,
updated locally when the daemon processes identity requests.
Initial data comes from session_sync/state_restore on WS connect.
"""
import threading


def _sync_score_to_daemon(pid: str, score: int):
    """Sync a single restored score to the authoritative daemon.scores singleton."""
    from daemon.scores import scores as daemon_scores
    daemon_scores.scores[pid] = score


def _sync_scores_to_daemon(scores_dict: dict):
    """Sync all restored scores to the authoritative daemon.scores singleton."""
    from daemon.scores import scores as daemon_scores
    daemon_scores.scores.clear()
    daemon_scores.scores.update(scores_dict)


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
        self.online_participants: set[str] = set()
        self.scores: dict[str, int] = {}
        self.locations: dict[str, str] = {}
        self.location_timezones: dict[str, str] = {}
        self.location_countries: dict[str, str] = {}
        self.mode: str = "workshop"
        self.current_activity: str = "none"
        self.emoji_counters: dict[str, int] = {}
        # Engagement: uuid -> {view -> {seconds, visits, clicks}} (cumulative, persisted)
        self.engagement: dict[str, dict] = {}
        # Liveness (ephemeral, NOT persisted): host derives "active now" from these
        self.last_active_at: dict[str, float] = {}
        self.last_view: dict[str, str] = {}

    def sync_from_restore(self, data: dict):
        """Update cache from state_restore or session_sync data.

        Uses in-place clear+update to preserve dict object identity so that
        router handlers holding a reference to the same dict object don't
        silently lose their writes.
        """
        with self._lock:
            participants = data.get("participants")
            if isinstance(participants, dict):
                self.participant_names.clear()
                self.participant_avatars.clear()
                self.online_participants.clear()
                self.scores.clear()
                self.locations.clear()
                self.location_timezones.clear()
                self.location_countries.clear()
                self.engagement.clear()
                for pid, raw in participants.items():
                    if not isinstance(raw, dict):
                        continue
                    name = raw.get("name")
                    if isinstance(name, str):
                        self.participant_names[str(pid)] = name
                    avatar = raw.get("avatar")
                    if isinstance(avatar, str):
                        self.participant_avatars[str(pid)] = avatar
                    score = raw.get("score")
                    if isinstance(score, (int, float)):
                        self.scores[str(pid)] = int(score)
                        _sync_score_to_daemon(str(pid), int(score))
                    location = raw.get("location")
                    if isinstance(location, str):
                        self.locations[str(pid)] = location
                    location_tz = raw.get("location_tz")
                    if isinstance(location_tz, str):
                        self.location_timezones[str(pid)] = location_tz
                    location_country = raw.get("location_country")
                    if isinstance(location_country, str):
                        self.location_countries[str(pid)] = location_country
                    engagement = raw.get("engagement")
                    if isinstance(engagement, dict):
                        self.engagement[str(pid)] = engagement
            else:
                self.online_participants.clear()
                if "participant_names" in data:
                    self.participant_names.clear()
                    self.participant_names.update(data["participant_names"])
                if "participant_avatars" in data:
                    self.participant_avatars.clear()
                    self.participant_avatars.update(data["participant_avatars"])
                if "online_participants" in data and isinstance(data["online_participants"], (list, set, tuple)):
                    self.online_participants.clear()
                    self.online_participants.update(str(pid) for pid in data["online_participants"])
                if "scores" in data:
                    self.scores.clear()
                    self.scores.update(data["scores"])
                    _sync_scores_to_daemon(data["scores"])
                if "locations" in data:
                    self.locations.clear()
                    self.locations.update(data["locations"])
                if "location_timezones" in data:
                    self.location_timezones.clear()
                    self.location_timezones.update(data["location_timezones"])
                if "location_countries" in data:
                    self.location_countries.clear()
                    self.location_countries.update(data["location_countries"])
            if "mode" in data:
                self.mode = data["mode"]
            if "current_activity" in data:
                self.current_activity = str(data["current_activity"])
            raw_emoji_counters = data.get("emoji_counters")
            if isinstance(raw_emoji_counters, dict):
                self.emoji_counters.clear()
                self.emoji_counters.update({k: v for k, v in raw_emoji_counters.items() if isinstance(v, int)})

    def snapshot(self) -> dict:
        """Return a copy of all state (for testing/debugging)."""
        with self._lock:
            return {
                "participant_names": dict(self.participant_names),
                "participant_avatars": dict(self.participant_avatars),
                "online_participants": sorted(self.online_participants),
                "scores": dict(self.scores),
                "locations": dict(self.locations),
                "location_timezones": dict(self.location_timezones),
                "location_countries": dict(self.location_countries),
                "mode": self.mode,
                "current_activity": self.current_activity,
                "emoji_counters": dict(self.emoji_counters),
                "engagement": {pid: dict(views) for pid, views in self.engagement.items()},
            }

    def reset(self, *, mode: str = "workshop") -> None:
        """Reset participant-related runtime state for a fresh session."""
        with self._lock:
            self.participant_names.clear()
            self.participant_avatars.clear()
            self.participant_universes.clear()
            self.online_participants.clear()
            self.scores.clear()
            self.locations.clear()
            self.location_timezones.clear()
            self.location_countries.clear()
            self.mode = mode
            self.current_activity = "none"
            self.emoji_counters.clear()
            self.engagement.clear()
            self.last_active_at.clear()
            self.last_view.clear()


# Module-level singleton
participant_state = ParticipantState()
