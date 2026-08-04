import json
import subprocess
import sys
import time as _time
from pathlib import Path

import pytest

from daemon import files_md, github_client, relink_open_files


@pytest.fixture
def tz_bucharest(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Bucharest")
    _time.tzset()
    yield
    monkeypatch.delenv("TZ", raising=False)
    _time.tzset()


def _tree(*paths):
    return github_client.RepoTree(paths=frozenset(paths), truncated=False)


def _seed(folder: Path, entries):
    doc = files_md.Doc(repos=[files_md.Repo(
        url="https://github.com/owner/repo", name="repo",
        default_branch="master", branch="solved", entries=entries)])
    (folder / files_md.session_filename()).write_text(doc.render(), encoding="utf-8")


def test_relink_upgrades_a_now_pushed_file(tmp_path, monkeypatch, tz_bucharest):
    _seed(tmp_path, [files_md.Entry(path="src/a.py", branch="solved",
                                    ts="2026-08-04T06:41:07Z", reason="not-pushed")])
    monkeypatch.setattr(github_client, "get_repo_info",
                        lambda o, r: github_client.RepoInfo(default_branch="master"))
    monkeypatch.setattr(github_client, "get_repo_tree",
                        lambda o, r, b: _tree("src/a.py") if b == "solved" else _tree())

    summary = relink_open_files.relink_folder(tmp_path)

    text = (tmp_path / files_md.session_filename()).read_text()
    assert "blob/solved/src/a.py" in text
    assert summary == {"repos": 1, "entries": 1, "linked_branch": 1,
                       "linked_default": 0, "unlinked": 0}


def test_relink_degrades_a_link_whose_branch_vanished(tmp_path, monkeypatch, tz_bucharest):
    _seed(tmp_path, [files_md.Entry(
        path="src/a.py", branch="solved", ts="2026-08-04T06:41:07Z",
        blob_url="https://github.com/owner/repo/blob/solved/src/a.py", ref="branch")])
    monkeypatch.setattr(github_client, "get_repo_info",
                        lambda o, r: github_client.RepoInfo(default_branch="master"))
    monkeypatch.setattr(github_client, "get_repo_tree",
                        lambda o, r, b: _tree("other.py") if b == "master" else None)
    monkeypatch.setattr(github_client, "head_blob", lambda o, r, b, p: False)

    summary = relink_open_files.relink_folder(tmp_path)

    text = (tmp_path / files_md.session_filename()).read_text()
    assert "blob/solved" not in text
    assert "reason:no-branch" in text
    assert summary["unlinked"] == 1


def test_relink_preserves_timestamps(tmp_path, monkeypatch, tz_bucharest):
    _seed(tmp_path, [files_md.Entry(path="src/a.py", branch="solved",
                                    ts="2026-08-04T06:41:07Z", reason="not-pushed")])
    monkeypatch.setattr(github_client, "get_repo_info",
                        lambda o, r: github_client.RepoInfo(default_branch="master"))
    monkeypatch.setattr(github_client, "get_repo_tree", lambda o, r, b: _tree("src/a.py"))

    relink_open_files.relink_folder(tmp_path)

    assert "ts:2026-08-04T06:41:07Z" in (tmp_path / files_md.session_filename()).read_text()


def test_relink_skips_a_repo_that_went_private(tmp_path, monkeypatch, tz_bucharest):
    _seed(tmp_path, [files_md.Entry(
        path="src/a.py", branch="solved", ts="2026-08-04T06:41:07Z",
        blob_url="https://github.com/owner/repo/blob/solved/src/a.py", ref="branch")])
    monkeypatch.setattr(github_client, "get_repo_info", lambda o, r: None)

    summary = relink_open_files.relink_folder(tmp_path)

    # Entries are left exactly as they were rather than silently unlinked:
    # a 404 here is far more likely a token/network problem than a real change.
    assert "blob/solved/src/a.py" in (tmp_path / files_md.session_filename()).read_text()
    assert summary["entries"] == 0


def test_relink_steady_state_does_not_touch_the_file(tmp_path, monkeypatch, tz_bucharest):
    # Nothing about this entry will change on relink: it already resolves to
    # exactly the same blob_url/ref it already had. The write must be skipped
    # entirely — an mtime bump here would make the daemon's file-watcher
    # broadcast a Files-tab update to every participant for no reason, since
    # the summarizer runs this pass on every summary generation.
    _seed(tmp_path, [files_md.Entry(
        path="src/a.py", branch="solved", ts="2026-08-04T06:41:07Z",
        blob_url="https://github.com/owner/repo/blob/solved/src/a.py", ref="branch")])
    monkeypatch.setattr(github_client, "get_repo_info",
                        lambda o, r: github_client.RepoInfo(default_branch="master"))
    monkeypatch.setattr(github_client, "get_repo_tree",
                        lambda o, r, b: _tree("src/a.py") if b == "solved" else _tree())

    target = tmp_path / files_md.session_filename()
    mtime_before = target.stat().st_mtime_ns

    summary = relink_open_files.relink_folder(tmp_path)

    assert target.stat().st_mtime_ns == mtime_before
    assert summary == {"repos": 1, "entries": 1, "linked_branch": 1,
                       "linked_default": 0, "unlinked": 0}


def test_relink_missing_file_returns_zero_summary(tmp_path):
    assert relink_open_files.relink_folder(tmp_path) == {
        "repos": 0, "entries": 0, "linked_branch": 0, "linked_default": 0, "unlinked": 0}


def test_cli_prints_json_summary(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "daemon.relink_open_files",
         "--session-folder", str(tmp_path)],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout)["entries"] == 0
