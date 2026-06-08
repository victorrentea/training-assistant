"""Tests for the per-participant sliding-window emoji rate limiter."""

from daemon.emoji.rate_limit import SlidingWindowRateLimiter


def test_burst_up_to_limit_allowed():
    rl = SlidingWindowRateLimiter(max_events=15, window_seconds=60.0)
    # 15 reactions fired at the same instant — all allowed (a burst).
    assert all(rl.allow("p1", now=100.0) for _ in range(15))


def test_sixteenth_in_window_rejected():
    rl = SlidingWindowRateLimiter(max_events=15, window_seconds=60.0)
    for _ in range(15):
        assert rl.allow("p1", now=100.0)
    # The 16th within the same minute is rejected.
    assert rl.allow("p1", now=130.0) is False


def test_window_slides_frees_capacity():
    rl = SlidingWindowRateLimiter(max_events=15, window_seconds=60.0)
    for _ in range(15):
        rl.allow("p1", now=100.0)
    assert rl.allow("p1", now=159.0) is False  # still inside the 60s window
    # Once the original burst ages out, capacity returns.
    assert rl.allow("p1", now=161.0) is True


def test_keys_are_independent():
    rl = SlidingWindowRateLimiter(max_events=15, window_seconds=60.0)
    for _ in range(15):
        rl.allow("p1", now=100.0)
    assert rl.allow("p1", now=100.0) is False
    # A different participant is unaffected.
    assert rl.allow("p2", now=100.0) is True


def test_reset_clears_state():
    rl = SlidingWindowRateLimiter(max_events=2, window_seconds=60.0)
    assert rl.allow("p1", now=0.0)
    assert rl.allow("p1", now=0.0)
    assert rl.allow("p1", now=0.0) is False
    rl.reset()
    assert rl.allow("p1", now=0.0) is True
