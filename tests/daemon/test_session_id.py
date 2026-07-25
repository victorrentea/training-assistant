"""Tests for CSPRNG-based session-ID generation (fix #6)."""
from unittest.mock import patch

from daemon.session.router import (
    _SESSION_ID_ALPHABET,
    _SESSION_ID_LEN,
    _generate_session_id,
)


def test_id_has_expected_length():
    assert _SESSION_ID_LEN >= 10
    assert len(_generate_session_id()) == _SESSION_ID_LEN


def test_id_uses_unambiguous_url_safe_alphabet():
    # No visually confusable chars (l, o, O, 0) and every char is URL-safe.
    for banned in ("l", "o", "O", "0"):
        assert banned not in _SESSION_ID_ALPHABET
    for _ in range(200):
        sid = _generate_session_id()
        assert all(ch in _SESSION_ID_ALPHABET for ch in sid)
        assert all(ch.isalnum() and ch.isascii() for ch in sid)  # URL-safe


def test_ids_are_distinct_across_many_draws():
    ids = {_generate_session_id() for _ in range(1000)}
    # ~50 bits of entropy → collisions in 1000 draws are astronomically unlikely.
    assert len(ids) == 1000


def test_uses_secrets_csprng_not_random():
    """Regression: generation must go through secrets (CSPRNG), not random."""
    with patch("daemon.session.router.secrets.choice", wraps=__import__("secrets").choice) as spy:
        _generate_session_id()
    assert spy.call_count == _SESSION_ID_LEN
