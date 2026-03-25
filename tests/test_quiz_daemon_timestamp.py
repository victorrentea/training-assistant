from pathlib import Path

from training_daemon import TranscriptTimestampAppender


def test_timestamp_appender_logs_missing_transcript_once(tmp_path: Path, capsys):
    appender = TranscriptTimestampAppender(folder=tmp_path, interval_seconds=3)

    appender.start()
    appender.tick()
    appender.tick()

    out = capsys.readouterr()
    assert "no .txt transcript found" in out.err
    assert out.err.count("no .txt transcript found") == 1


def test_timestamp_appender_appends_on_interval(tmp_path: Path):
    transcript = tmp_path / "session.txt"
    transcript.write_text("[ 00:00:22.50 ] Victor:\tHello", encoding="utf-8")

    appender = TranscriptTimestampAppender(folder=tmp_path, interval_seconds=0.01)
    appender.start()

    assert appender.enabled is True

    appender.tick()
    first = transcript.read_text(encoding="utf-8")
    assert "\n[ " in first
    assert "Victor" not in first.splitlines()[-1]

    appender.tick()
    second = transcript.read_text(encoding="utf-8")
    assert second == first

