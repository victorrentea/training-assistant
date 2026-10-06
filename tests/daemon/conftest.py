"""Shared fixtures for daemon tests."""
import os

# The soundboard apps on this Mac (Victor Addons :55123 → Victor Effects) have no
# auth and are live during a workshop, so a test run that reaches them plays a
# real sound in front of a real room. It happened: an unmocked host Test-button
# test pressed tile 69 (the default, the ghost) on every suite run — while the
# room had the doorbell selected. Point the client at the discard port before
# any daemon module is imported, so even an unmocked press is refused instantly.
_NOWHERE = "http://127.0.0.1:9"
os.environ["VICTOR_ADDONS_URL"] = _NOWHERE

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def never_reach_the_real_soundboard(monkeypatch):
    """Belt and braces for the env var above: if `effects_client` was imported
    before this conftest (a plugin, a stray import), its URL was already read."""
    from daemon import effects_client
    monkeypatch.setattr(effects_client, "EFFECTS_BASE_URL", _NOWHERE)


@pytest.fixture(autouse=True)
def reset_quiz_state():
    """Reset the global quiz_state singleton before each test to prevent cross-test contamination."""
    from daemon.quiz.state import quiz_state
    quiz_state.clear()
    yield
    quiz_state.clear()


@pytest.fixture(autouse=True)
def reset_module_level_throttles():
    """Module-level throttles and rate buckets remember wall-clock time, so one
    test's burst would otherwise throttle the next. Only resets modules a test
    already imported — the fixture itself must not pull in daemon modules."""
    import sys

    def _reset():
        fanout = sys.modules.get("daemon.participant.fanout")
        if fanout is not None:
            for name in ("active_count", "host_roster"):
                throttle = getattr(fanout, name, None)
                if throttle is not None:
                    throttle.reset()
        emoji_router = sys.modules.get("daemon.emoji.router")
        if emoji_router is not None:
            emoji_router.emoji_global_bucket.reset()

    _reset()
    yield
    _reset()
