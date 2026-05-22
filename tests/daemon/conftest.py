"""Shared fixtures for daemon tests."""
import pytest


@pytest.fixture(autouse=True)
def reset_quiz_state():
    """Reset the global quiz_state singleton before each test to prevent cross-test contamination."""
    from daemon.quiz.state import quiz_state
    quiz_state.clear()
    yield
    quiz_state.clear()
