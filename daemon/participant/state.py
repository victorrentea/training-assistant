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
        # Explicit anonymity signal: pids that joined via the auto-assign path
        # (empty/blank name → fictional-pool name) and have NOT since typed a
        # real name. Drives the attendees.md "(anonymous)" tag and the bell's
        # anonymous flag WITHOUT guessing from pool membership (so a participant
        # who deliberately types "Frodo" is never mis-tagged). Persisted so the
        # tag survives a daemon restart / reconnect.
        self.anonymous_pids: set[str] = set()
        # UUIDs that proved they run on the trainer's machine by calling the
        # loopback-only claim endpoint (daemon/host_machine/router.py). Holding
        # the reserved trainer name is gated on membership here. Persisted so
        # the trainer keeps it across a daemon restart within the same session.
        self.trainer_pids: set[str] = set()
        self.online_participants: set[str] = set()
        self.scores: dict[str, int] = {}
        self.locations: dict[str, str] = {}
        self.location_timezones: dict[str, str] = {}
        self.location_countries: dict[str, str] = {}
        self.mode: str = "workshop"
        self.current_activity: str = "none"
        self.emoji_counters: dict[str, int] = {}
        # Session-wide master switch: when False, the daemon silently drops all
        # incoming emoji reactions (host screen + desktop overlay). Persisted.
        self.emoji_global_enabled: bool = True
        # Session-wide master switch for the whole "attention" capability (both
        # directions: participant→host bell + host→participant OS notifications).
        # Unlike the emoji switch it DEFAULTS OFF and resets OFF every session —
        # the host must explicitly opt in from the host UI. Persisted.
        self.attention_enabled: bool = False
        # Engagement: uuid -> {view -> {seconds, visits, clicks}} (cumulative, persisted)
        self.engagement: dict[str, dict] = {}
        # Liveness (ephemeral, NOT persisted): host derives "active now" from these
        self.last_active_at: dict[str, float] = {}
        self.last_view: dict[str, str] = {}
        # Sorted name multiset of the last participant_names_updated broadcast
        # (ephemeral, NOT persisted). Roster notifications fire on every activity
        # heartbeat, but names only change on register/rename — the router skips
        # re-broadcasting an unchanged multiset. Lives here (not module-level in
        # the router) so reset()/sync_from_restore() invalidate it with the roster.
        self.last_broadcast_names: list[str] | None = None

    def sync_from_restore(self, data: dict):
        """Update cache from state_restore or session_sync data.

        Uses in-place clear+update to preserve dict object identity so that
        router handlers holding a reference to the same dict object don't
        silently lose their writes.
        """
        with self._lock:
            # Roster may be replaced wholesale — force the next names broadcast.
            self.last_broadcast_names = None
            # Restore the explicit anonymity signal. A snapshot that omits it
            # (legacy file) leaves everyone untagged rather than guessing from
            # pool membership — prefer under-tagging over mis-tagging a real name.
            _anon = data.get("anonymous_pids")
            if isinstance(_anon, (list, set, tuple)):
                self.anonymous_pids = {str(p) for p in _anon}
            elif isinstance(data.get("participants"), dict):
                self.anonymous_pids.clear()
            _trainers = data.get("trainer_pids")
            if isinstance(_trainers, (list, set, tuple)):
                self.trainer_pids = {str(p) for p in _trainers}
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
            if isinstance(data.get("emoji_global_enabled"), bool):
                self.emoji_global_enabled = data["emoji_global_enabled"]
            # A restore that omits the flag leaves it at its safe default (OFF).
            if isinstance(data.get("attention_enabled"), bool):
                self.attention_enabled = data["attention_enabled"]

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
                "emoji_global_enabled": self.emoji_global_enabled,
                "attention_enabled": self.attention_enabled,
                "engagement": {pid: dict(views) for pid, views in self.engagement.items()},
                # Explicit anonymity signal — persisted so the "(anonymous)" tag
                # and the bell's anonymous flag survive a daemon restart.
                "anonymous_pids": sorted(self.anonymous_pids),
                # Who may hold the reserved trainer name — persisted so a daemon
                # restart mid-session doesn't silently demote the trainer.
                "trainer_pids": sorted(self.trainer_pids),
            }

    def persist(self) -> None:
        """Persist a snapshot of this state to the active session folder.

        No-op while no session is active. Single home for the
        get-folder + save_session_state(snapshot) idiom the feature routers
        (emoji, attention, …) all need after mutating persisted fields.
        """
        # Deferred imports: keep this low-level state module import-light.
        from daemon.misc.content_files import get_active_session_folder
        from daemon.session_state import save_session_state
        folder = get_active_session_folder()
        if folder:
            save_session_state(folder, self.snapshot())

    def reset(self, *, mode: str = "workshop") -> None:
        """Reset participant-related runtime state for a fresh session."""
        with self._lock:
            self.participant_names.clear()
            self.participant_avatars.clear()
            self.participant_universes.clear()
            self.anonymous_pids.clear()
            self.trainer_pids.clear()
            self.online_participants.clear()
            self.scores.clear()
            self.locations.clear()
            self.location_timezones.clear()
            self.location_countries.clear()
            self.mode = mode
            self.current_activity = "none"
            self.emoji_counters.clear()
            self.emoji_global_enabled = True
            # Attention always starts OFF — every session is explicit opt-in.
            self.attention_enabled = False
            self.engagement.clear()
            self.last_active_at.clear()
            self.last_view.clear()
            self.last_broadcast_names = None
        # Outside the lock (avoids holding it across imports): clear per-session
        # rate limiters so a returning UUID doesn't eat a stale 429 in a fresh
        # session. See _reset_session_limiters for the leak this closes.
        self._reset_session_limiters()

    @staticmethod
    def _reset_session_limiters() -> None:
        """Clear module-level per-participant rate limiters on session reset.

        The bell + emoji limiters are keyed by participant UUID and live at
        module scope, so without this a UUID that hit its cap in the previous
        session would start the next one already throttled. Deferred imports
        keep this state module free of router (FastAPI) import cost and avoid a
        circular import at load time; failures are swallowed because a missing
        limiter must never break a session reset.
        """
        try:
            from daemon.attention.router import bell_rate_limiter
            bell_rate_limiter.reset()
        except Exception:
            pass
        try:
            from daemon.emoji.router import emoji_rate_limiter
            emoji_rate_limiter.reset()
        except Exception:
            pass


# Module-level singleton
participant_state = ParticipantState()
