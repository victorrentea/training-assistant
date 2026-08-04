"""Tests for daemon.addon_bridge_client helper functions."""


def test_addon_git_file_opened_calls_files_md(monkeypatch):
    from daemon import files_md
    from daemon.addon_bridge_client import _handle_git_file_opened

    calls: list[tuple] = []
    monkeypatch.setattr(
        files_md, "record_file_opened",
        lambda url, branch, file_path: calls.append((url, branch, file_path)),
    )

    _handle_git_file_opened({
        "type": "git_file_opened",
        "url": "https://github.com/owner/repo",
        "branch": "main",
        "file": "src/a.py",
    })

    assert calls == [("https://github.com/owner/repo", "main", "src/a.py")]


def test_addon_git_file_opened_drops_empty_url_or_file(monkeypatch):
    from daemon import files_md
    from daemon.addon_bridge_client import _handle_git_file_opened

    calls: list[tuple] = []
    monkeypatch.setattr(
        files_md, "record_file_opened",
        lambda url, branch, file_path: calls.append((url, branch, file_path)),
    )

    _handle_git_file_opened({"type": "git_file_opened", "url": "", "file": "src/a.py"})
    _handle_git_file_opened({"type": "git_file_opened", "url": "https://x", "file": ""})

    assert calls == []
