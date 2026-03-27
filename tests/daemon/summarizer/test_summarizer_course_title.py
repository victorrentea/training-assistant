import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from daemon.config import Config
from daemon.summary.summarizer import generate_summary, _normalize_course_title


def _cfg(tmp_path: Path) -> Config:
    return Config(
        folder=tmp_path,
        minutes=30,
        server_url="http://localhost",
        api_key="key",
        model="model",
        dry_run=False,
        host_username="h",
        host_password="p",
    )


def test_normalize_course_title_removes_date_prefix():
    assert _normalize_course_title("2026-03-26 Clean Code") == "Clean Code"
    assert _normalize_course_title("20260326: JPA") == "JPA"
    assert _normalize_course_title("2026.03.26 09:30 - Spring") == "Spring"


@patch("daemon.summary.summarizer.get_project_tools", return_value=[])
@patch("daemon.summary.summarizer.read_session_notes", return_value="")
@patch("daemon.summary.summarizer.extract_all_text", return_value="Transcript line")
@patch("daemon.summary.summarizer.load_transcription_files", return_value=[("t", "x")])
@patch("daemon.summary.summarizer.create_message")
def test_generate_summary_includes_clean_course_title(
    mock_create, *_mocks
):
    mock_resp = MagicMock()
    mock_resp.stop_reason = "end_turn"
    mock_resp.content = [MagicMock(type="text", text="[]")]
    mock_create.return_value = mock_resp

    with tempfile.TemporaryDirectory() as d:
        result = generate_summary(
            _cfg(Path(d)),
            existing_points=[],
            since_entry=0,
            course_title="2026-03-26 Design Patterns",
        )

    assert result is not None
    sent_prompt = mock_create.call_args.kwargs["messages"][0]["content"]
    assert "COURSE TITLE (without date prefix): Design Patterns" in sent_prompt
    assert "2026-03-26 Design Patterns" not in sent_prompt
