from daemon import log


def test_progress_logs_replace_last_line_instead_of_appending(capsys):
    log.info("intellij", "Git +5s: java-memory @ main (total: 70s)")
    log.info("intellij", "Git +5s: java-memory @ main (total: 75s)")
    log.info("daemon", "next regular line")

    out = capsys.readouterr().out
    assert "Git +5s: java-memory @ main (total: 70s)\n" not in out
    assert "Git +5s: java-memory @ main (total: 70s)\r" in out
    assert "Git +5s: java-memory @ main (total: 75s)" in out
