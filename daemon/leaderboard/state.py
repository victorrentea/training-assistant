"""Leaderboard active/data state for daemon — tracks whether overlay is visible."""


class LeaderboardState:
    def __init__(self):
        self.active: bool = False
        self.data: list[dict] | None = None  # last-shown leaderboard entries

    def show(self, entries: list[dict], total_participants: int):
        self.active = True
        self.data = {"entries": entries, "total_participants": total_participants}

    def hide(self):
        self.active = False
        # Keep data so participants reconnecting mid-display can still see it


# Module-level singleton
leaderboard_state = LeaderboardState()
