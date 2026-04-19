"""Shared fixtures for daemon tests."""
import pytest


@pytest.fixture(autouse=True)
def reset_poll_state():
    """Reset the global poll_state singleton before each test to prevent cross-test contamination."""
    from daemon.poll.state import poll_state
    poll_state.clear()
    yield
    poll_state.clear()
