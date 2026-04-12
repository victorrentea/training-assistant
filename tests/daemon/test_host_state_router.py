import datetime as dt

from daemon import host_state_router


def test_build_slides_log_fields_uses_active_session_entry(monkeypatch):
    captured = {}

    def _fake_read(folder, session_date, session_entry):
        captured["session_entry"] = session_entry
        return []

    monkeypatch.setattr(host_state_router.session_shared_state, "get_active_session_name", lambda: "active")
    monkeypatch.setattr(host_state_router, "read_slides_log", _fake_read)

    host_state_router._build_slides_log_fields()

    assert captured["session_entry"] == {"name": "active"}


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
