"""Per-participant sliding-window rate limiter for emoji reactions.

Allows an instant burst up to ``max_events`` but never more than that in any
rolling ``window_seconds`` window — so a participant can fire off 15 quick
reactions, but not spam continuously.
"""
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        """Record a hit for ``key`` and return whether it is within the limit.

        Returns False (and records nothing) once ``max_events`` hits already
        fall inside the trailing window.
        """
        now = time.monotonic() if now is None else now
        cutoff = now - self.window_seconds
        self._prune(cutoff)
        hits = self._hits[key]
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self.max_events:
            return False
        hits.append(now)
        return True

    def _prune(self, cutoff: float) -> None:
        """Evict keys whose whole window has expired.

        Keeps memory bounded by *currently active* senders instead of growing
        one deque per lifetime-distinct participant id.
        """
        stale = [k for k, h in self._hits.items() if not h or h[-1] <= cutoff]
        for k in stale:
            del self._hits[k]

    def reset(self) -> None:
        """Forget all recorded hits — used by tests for isolation."""
        self._hits.clear()
