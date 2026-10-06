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


class TokenBucket:
    """One shared bucket: up to ``burst`` events at once, refilled at ``rate_per_s``.

    Caps the TOTAL rate across all keys, which a per-key limiter cannot do when
    the keys are chosen by the caller.
    """

    def __init__(self, burst: float, rate_per_s: float):
        self.burst = burst
        self.rate_per_s = rate_per_s
        self._tokens = float(burst)
        self._updated: float | None = None

    def allow(self, now: float | None = None) -> bool:
        """Take one token if there is one. Returns False (and takes nothing) when empty."""
        now = time.monotonic() if now is None else now
        if self._updated is not None:
            elapsed = max(0.0, now - self._updated)
            self._tokens = min(float(self.burst), self._tokens + elapsed * self.rate_per_s)
        self._updated = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def reset(self) -> None:
        """Refill the bucket — used by tests for isolation."""
        self._tokens = float(self.burst)
        self._updated = None
