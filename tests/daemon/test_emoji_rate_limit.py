"""Tests for the per-participant sliding-window emoji rate limiter."""

from daemon.emoji.rate_limit import SlidingWindowRateLimiter, TokenBucket


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


# ── Global token bucket (cap across ALL participants) ─────────────────────────


def test_bucket_allows_a_burst_then_refuses():
    b = TokenBucket(burst=20, rate_per_s=8)
    assert all(b.allow(now=100.0) for _ in range(20))
    assert b.allow(now=100.0) is False


def test_bucket_refills_at_the_configured_rate():
    b = TokenBucket(burst=20, rate_per_s=8)
    for _ in range(20):
        b.allow(now=100.0)
    # 0.5 s later: 4 tokens back, no more.
    assert [b.allow(now=100.5) for _ in range(5)] == [True, True, True, True, False]


def test_bucket_never_holds_more_than_the_burst():
    b = TokenBucket(burst=3, rate_per_s=8)
    b.allow(now=0.0)
    # A long idle period refills to the burst size, not beyond.
    assert [b.allow(now=1000.0) for _ in range(4)] == [True, True, True, False]


def test_bucket_sustained_rate_is_capped():
    b = TokenBucket(burst=20, rate_per_s=8)
    # 100 reactions/s for 10 s from rotating ids: about 20 + 8*10 get through.
    allowed = sum(b.allow(now=i / 100) for i in range(1000))
    assert 95 <= allowed <= 102


def test_bucket_reset_refills():
    b = TokenBucket(burst=1, rate_per_s=0.001)
    assert b.allow(now=0.0)
    assert b.allow(now=0.0) is False
    b.reset()
    assert b.allow(now=0.0) is True
