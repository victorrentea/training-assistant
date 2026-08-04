"""Lightweight in-memory IP rate limiting for session-probe / status endpoints.

The public session-status endpoints (`/{id}/api/status`, `/api/status`,
`/api/is-active-session`) and the participant page route act as a 200-vs-404
enumeration oracle for guessable session ids. Without any inbound throttling an
attacker can probe them at ~1500 req/s to brute-force live session ids.

This module implements a per-IP token bucket that blunts such floods while
leaving a generous budget for legitimate participants (who poll status only
every few seconds). It is deliberately simple (in-process, best-effort) — it is
defense-in-depth, not a hard security boundary.

Loopback peers (health checks, local e2e harness) are exempted so the real
uvicorn test suite and internal probes are never throttled. Behind Railway's
proxy real participants always present a non-loopback socket peer and are keyed
by the leftmost X-Forwarded-For hop (their real client IP), so each participant
gets an independent budget.
"""
import os
import threading
import time

from fastapi import HTTPException, Request

# Per-IP budget. Generous enough that a participant polling status a few times a
# second never trips it, but a 1500 req/s flood is throttled to the refill rate.
_CAPACITY = int(os.environ.get("RATE_LIMIT_CAPACITY", "60"))
_REFILL_PER_SEC = float(os.environ.get("RATE_LIMIT_REFILL_PER_SEC", "15"))

# Socket peers that are never rate-limited (internal / test harness). Note this
# is the real TCP peer (request.client.host), which cannot be spoofed by an
# X-Forwarded-For header; in production the peer is Railway's proxy, never these.
_EXEMPT_PEERS = {"127.0.0.1", "::1", "localhost"}


class TokenBucketLimiter:
    """Thread-safe per-key token bucket.

    Each key (client IP) starts with ``capacity`` tokens and refills at
    ``refill_per_sec`` tokens/second up to ``capacity``. Each allowed request
    consumes one token; when the bucket is empty the request is rejected.
    """

    def __init__(self, capacity: int, refill_per_sec: float):
        self.capacity = float(capacity)
        self.refill_per_sec = float(refill_per_sec)
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_ts)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill_per_sec)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                return True
            self._buckets[key] = (tokens, now)
            return False

    def reset(self) -> None:
        """Drop all per-key state (used by tests and on config changes)."""
        with self._lock:
            self._buckets.clear()


# Shared limiter for all session-probe / status endpoints.
probe_limiter = TokenBucketLimiter(_CAPACITY, _REFILL_PER_SEC)


def _client_key(request: Request) -> str:
    """Key requests by the participant's real client IP (leftmost XFF hop)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _is_exempt(request: Request) -> bool:
    peer = request.client.host if request.client else ""
    return peer in _EXEMPT_PEERS


async def rate_limit_probe(request: Request) -> None:
    """FastAPI dependency: throttle session-probe/status endpoints per client IP.

    Declared BEFORE session-validation dependencies so that even invalid-session
    probes (which would otherwise short-circuit to 404) are counted against the
    attacker's budget — otherwise the enumeration oracle stays unthrottled.
    """
    if os.environ.get("GATEWAY_RATE_LIMIT_DISABLED") == "1":
        return
    if _is_exempt(request):
        return
    if not probe_limiter.allow(_client_key(request)):
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": "1"},
        )


# Drive-relay downloads are the one endpoint where a single request can cost
# hundreds of megabytes of egress, so it gets its own far stricter budget than
# the probe endpoints: three downloads, then one more every five minutes.
_DRIVE_ZIP_CAPACITY = int(os.environ.get("DRIVE_ZIP_RATE_CAPACITY", "3"))
_DRIVE_ZIP_REFILL_PER_SEC = float(
    os.environ.get("DRIVE_ZIP_RATE_REFILL_PER_SEC", str(1.0 / 300.0))
)

drive_zip_limiter = TokenBucketLimiter(_DRIVE_ZIP_CAPACITY, _DRIVE_ZIP_REFILL_PER_SEC)


async def rate_limit_drive_zip(request: Request) -> None:
    """FastAPI dependency: throttle Drive-relay zip downloads per client IP."""
    if os.environ.get("GATEWAY_RATE_LIMIT_DISABLED") == "1":
        return
    if _is_exempt(request):
        return
    if not drive_zip_limiter.allow(_client_key(request)):
        raise HTTPException(
            status_code=429,
            detail="Too many downloads — please wait a few minutes and try again",
            headers={"Retry-After": "300"},
        )
