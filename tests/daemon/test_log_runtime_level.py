from daemon import log


def test_debug_logging_can_be_switched_at_runtime(capsys):
    previous = log.get_level()
    try:
        log.set_level("info")
        log.debug("daemon", "hidden debug line")
        captured = capsys.readouterr()
        assert "hidden debug line" not in captured.out

        log.set_level("debug")
        log.debug("daemon", "visible debug line")
        captured = capsys.readouterr()
        assert "visible debug line" in captured.out
        assert "debug" in captured.out
    finally:
        log.set_level(previous)
