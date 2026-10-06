"""LoopThrottle: leading + trailing-edge throttle on the daemon event loop."""
import asyncio
import threading
import time

import pytest

from daemon import throttle as throttle_mod
from daemon.throttle import LoopThrottle

INTERVAL = 0.1


class _Probe:
    """Callback that records the value of `state` each time it runs."""

    def __init__(self):
        self.state = 0
        self.seen: list[int] = []

    async def __call__(self):
        self.seen.append(self.state)


@pytest.fixture
def background_loop(monkeypatch):
    """A running loop in its own thread, registered as the daemon loop."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(throttle_mod, "get_event_loop", lambda: loop)
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)
    loop.close()


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_first_request_runs_immediately_and_is_awaited():
    probe = _Probe()
    t = LoopThrottle("t", INTERVAL, probe)

    async def scenario():
        probe.state = 1
        await t.request()
        return list(probe.seen)

    assert asyncio.run(scenario()) == [1]


def test_burst_coalesces_into_one_trailing_run_with_the_final_state():
    probe = _Probe()
    t = LoopThrottle("t", INTERVAL, probe)

    async def scenario():
        for i in range(1, 51):
            probe.state = i
            await t.request()
        assert probe.seen == [1]  # leading edge only, the rest is booked
        await asyncio.sleep(INTERVAL * 2.5)
        return list(probe.seen)

    assert asyncio.run(scenario()) == [1, 50]


def test_runs_are_spaced_by_the_interval():
    stamps: list[float] = []

    async def stamped():
        stamps.append(time.monotonic())

    t = LoopThrottle("t", INTERVAL, stamped)

    async def scenario():
        end = time.monotonic() + INTERVAL * 4.5
        while time.monotonic() < end:
            await t.request()
            await asyncio.sleep(0.005)
        await asyncio.sleep(INTERVAL * 1.5)

    asyncio.run(scenario())
    assert 4 <= len(stamps) <= 7
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert min(gaps) >= INTERVAL * 0.9


def test_request_threadsafe_from_another_thread_coalesces(background_loop):
    probe = _Probe()
    t = LoopThrottle("t", INTERVAL, probe)

    for i in range(1, 501):
        probe.state = i
        assert t.request_threadsafe() is True

    assert _wait_until(lambda: probe.seen and probe.seen[-1] == 500)
    time.sleep(INTERVAL * 2)
    assert len(probe.seen) <= 3, probe.seen
    assert probe.seen[-1] == 500


def test_request_threadsafe_without_a_running_loop_reports_false(monkeypatch):
    monkeypatch.setattr(throttle_mod, "get_event_loop", lambda: None)
    probe = _Probe()
    assert LoopThrottle("t", INTERVAL, probe).request_threadsafe() is False
    assert probe.seen == []


def test_trailing_run_booked_on_a_dead_loop_is_rebooked():
    """Tests (TestClient) spin one loop per request; a timer booked on a loop
    that is gone must not block every later request."""
    probe = _Probe()
    t = LoopThrottle("t", 10.0, probe)

    async def leading_then_book():
        await t.request()  # leading
        await t.request()  # booked 10 s out, on this loop

    asyncio.run(leading_then_book())
    assert probe.seen == [0]

    t._last_run = float("-inf")  # pretend the interval has passed

    async def later():
        probe.state = 7
        await t.request()

    asyncio.run(later())
    assert probe.seen == [0, 7]


def test_callback_error_is_logged_not_raised(monkeypatch):
    errors = []
    monkeypatch.setattr(throttle_mod.log, "error", lambda name, msg: errors.append(msg))

    async def boom():
        raise RuntimeError("nope")

    asyncio.run(LoopThrottle("boom", INTERVAL, boom).request())
    assert errors and "boom" in errors[0] and "nope" in errors[0]
