from datetime import date

from daemon.session_state import session_day_is_over


def test_session_started_today_keeps_running():
    assert not session_day_is_over("2026-09-25", date(2026, 9, 25))


def test_session_ends_once_midnight_has_passed():
    assert session_day_is_over("2026-09-25", date(2026, 9, 26))


def test_session_ends_the_morning_after_when_laptop_was_off_at_midnight():
    assert session_day_is_over("2026-09-24", date(2026, 9, 26))


def test_unknown_start_day_never_ends_a_live_session():
    assert not session_day_is_over(None, date(2026, 9, 26))
    assert not session_day_is_over("garbage", date(2026, 9, 26))
