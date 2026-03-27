from datetime import time
from daemon.session_state import check_daily_timing as _check_daily_timing


def test_warning_window():
    assert _check_daily_timing(time(17, 30)) == "warning"
    assert _check_daily_timing(time(17, 59)) == "warning"
    assert _check_daily_timing(time(17, 29)) is None


def test_auto_pause_threshold():
    assert _check_daily_timing(time(18, 0)) == "auto_pause"
    assert _check_daily_timing(time(20, 0)) == "auto_pause"   # threshold, not window


def test_midnight():
    assert _check_daily_timing(time(23, 59)) == "midnight"
    assert _check_daily_timing(time(0, 0)) == "midnight"


def test_normal_day_times():
    assert _check_daily_timing(time(9, 0)) is None
    assert _check_daily_timing(time(12, 0)) is None
    assert _check_daily_timing(time(17, 29)) is None
