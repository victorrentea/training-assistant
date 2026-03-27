import tempfile, datetime
from pathlib import Path


def test_load_discussion_new_filename():
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        (folder / "transcript_discussion.md").write_text("---\nwatermark: 5\n---\n\nMon 10:00 Test point\n")
        from daemon.session_state import load_key_points as _load_key_points
        points, watermark = _load_key_points(folder)
        assert watermark == 5
        assert len(points) == 1
        assert "Test point" in points[0]["text"]


def test_load_discussion_falls_back_to_old_filename():
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        (folder / "transcript_keypoints.md").write_text("---\nwatermark: 3\n---\n\nMon 09:00 Legacy point\n")
        from daemon.session_state import load_key_points as _load_key_points
        points, watermark = _load_key_points(folder)
        assert watermark == 3


def test_save_discussion_writes_new_filename():
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        from daemon.session_state import save_key_points as _save_key_points
        _save_key_points(folder, [{"text": "Point A", "source": "discussion", "time": "10:00"}], 7, datetime.date.today())
        assert (folder / "transcript_discussion.md").exists()
        assert not (folder / "transcript_keypoints.md").exists()
