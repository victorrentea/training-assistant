"""Poll feature state — host draft + votes.

Mirrors the daemon/quiz/state.py pattern: module-level singleton, mutable
in place. Persistence via the 3-second session-state snapshot loop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel


class PollData(BaseModel):
    """Host-composed poll draft, also the live poll while running."""
    question: str
    options: list[str]
    multi: bool
    public: bool


@dataclass
class PollState:
    data: Optional[PollData] = None
    started: bool = False
    opened_at: Optional[str] = None
    votes: dict[str, dict] = field(default_factory=dict)
    # votes[participant_uuid] = {"option_indices": list[int], "voted_at": "ISO"}
    _vote_counts_cache: Optional[list[int]] = None
    _vote_counts_dirty: bool = True

    def cast_vote(self, pid: str, option_indices: list[int]) -> bool:
        """Cast or update a vote. Empty list removes the participant's entry.

        Returns True on accept, False on reject (not started, bad index, multi-vote-when-single).
        """
        if not self.started or self.data is None:
            return False
        n = len(self.data.options)
        for idx in option_indices:
            if idx < 0 or idx >= n:
                return False
        if not self.data.multi and len(option_indices) > 1:
            return False

        if not option_indices:
            self.votes.pop(pid, None)
        else:
            self.votes[pid] = {
                "option_indices": list(option_indices),
                "voted_at": datetime.now(timezone.utc).isoformat(),
            }
        self._vote_counts_dirty = True
        return True

    def vote_counts(self) -> list[int]:
        """Per-option tally. Cached; invalidated on every cast_vote and reset."""
        if not self._vote_counts_dirty and self._vote_counts_cache is not None:
            return self._vote_counts_cache
        n = len(self.data.options) if self.data else 0
        counts = [0] * n
        for v in self.votes.values():
            for idx in v["option_indices"]:
                if 0 <= idx < n:
                    counts[idx] += 1
        self._vote_counts_cache = counts
        self._vote_counts_dirty = False
        return counts

    def distinct_voter_count(self) -> int:
        return len(self.votes)

    def invalidate_counts(self) -> None:
        """Call after mutating .data (e.g. host edits) so vote_counts re-computes
        against the new options array length."""
        self._vote_counts_dirty = True

    def reset(self) -> None:
        self.data = None
        self.started = False
        self.opened_at = None
        self.votes.clear()
        self._vote_counts_cache = None
        self._vote_counts_dirty = True


poll_state = PollState()
