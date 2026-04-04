"""Leaderboard data state for daemon — tracks last-shown leaderboard entries."""


class LeaderboardState:
    def __init__(self):
        self.data: list[dict] | None = None  # last-shown leaderboard entries

    def show(self, entries: list[dict], total_participants: int):
        self.data = {"entries": entries, "total_participants": total_participants}


# Module-level singleton
leaderboard_state = LeaderboardState()
