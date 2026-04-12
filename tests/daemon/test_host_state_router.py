import datetime as dt

from daemon import host_state_router


def test_build_slides_log_fields_reads_from_misc_state(monkeypatch):
    from daemon.misc.state import misc_state
    misc_state.slides_viewed = [
        {"file_name": "AI.pptx", "page": 3, "seconds": 120},
        {"file_name": "AI.pptx", "page": 4, "seconds": 30},
    ]
    misc_state.slides_current = None
    from daemon.host_state_router import _build_slides_log_fields
    result = _build_slides_log_fields()
    assert result["slides_log_deep_count"] == 2
    assert len(result["slides_log"]) == 2
    assert result["slides_log"][0]["file"] == "AI.pptx"
    assert result["slides_log"][0]["seconds_spent"] == 120
    # Cleanup
    misc_state.slides_viewed = []


def test_build_git_repos_fields_parses_activity_git_file(monkeypatch, tmp_path):
    session_date = dt.date(2026, 4, 9)
    activity_file = tmp_path / f"activity-git-{session_date.isoformat()}.md"
    activity_file.write_text(
        "10:00:00 https://github.com/acme/repo-a branch:feature/one file:main.py\n"
        "10:00:00 https://github.com/acme/repo-a branch:feature/one file:README.md\n"
        "10:00:00 https://github.com/acme/repo-b branch:fix/two file:service.py\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("TRANSCRIPTION_FOLDER", str(tmp_path))
    monkeypatch.setattr(
        host_state_router,
        "_get_active_session_entry",
        lambda: {"name": "active", "started_at": "2026-04-09T08:00:00"},
    )

    fields = host_state_router._build_git_repos_fields()

    assert fields["git_repos_count"] == 2
    assert fields["git_repos"] == [
        {
            "url": "https://github.com/acme/repo-a",
            "branch": "feature/one",
            "files": ["README.md", "main.py"],
        },
        {
            "url": "https://github.com/acme/repo-b",
            "branch": "fix/two",
            "files": ["service.py"],
        },
    ]
