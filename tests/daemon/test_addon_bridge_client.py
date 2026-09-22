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


def test_session_started_carries_the_last_day_of_the_set():
    from daemon.addon_bridge_client import _session_started_msg

    msg = _session_started_msg("https://x/abc", "/s/2026-09-14..15 AI@Konecranes")

    assert msg["session_folder"] == "/s/2026-09-14..15 AI@Konecranes"
    assert msg["session_last_day"] == "2026-09-15"


def test_session_started_last_day_of_a_two_day_split_set():
    from daemon.addon_bridge_client import _session_started_msg

    # "+" = only those two days; the last one is still where the survey belongs.
    msg = _session_started_msg("https://x/abc", "/s/2026-09-4+9 AI@Nice")

    assert msg["session_last_day"] == "2026-09-09"


def test_session_started_single_day_set_is_its_own_last_day():
    from daemon.addon_bridge_client import _session_started_msg

    msg = _session_started_msg("https://x/abc", "/s/2026-09-22 AI@Acme")

    assert msg["session_last_day"] == "2026-09-22"


def test_session_started_omits_the_last_day_when_the_folder_has_no_dates():
    from daemon.addon_bridge_client import _session_started_msg

    msg = _session_started_msg("https://x/abc", "/s/AI@Acme")

    assert "session_last_day" not in msg
    assert msg["session_folder"] == "/s/AI@Acme"


def test_session_started_without_a_folder_is_url_only():
    from daemon.addon_bridge_client import _session_started_msg

    assert _session_started_msg("https://x/abc", None) == {
        "type": "session_started",
        "participant_url": "https://x/abc",
    }
