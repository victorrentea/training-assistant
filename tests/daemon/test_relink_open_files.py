import json
import subprocess
import sys
import time as _time
from pathlib import Path
from unittest.mock import patch

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
                       "linked_default": 0, "adopted_dominant": 0, "unlinked": 0, "skipped": 0}


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
    assert summary["skipped"] == 1


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
                       "linked_default": 0, "adopted_dominant": 0, "unlinked": 0, "skipped": 0}


def test_relink_missing_file_returns_zero_summary(tmp_path):
    assert relink_open_files.relink_folder(tmp_path) == {
        "repos": 0, "entries": 0, "linked_branch": 0, "linked_default": 0,
        "adopted_dominant": 0, "unlinked": 0, "skipped": 0}


def test_relink_unreadable_file_returns_zero_summary_instead_of_raising(tmp_path, monkeypatch):
    """Reproduces the file becoming unreadable between the exists() check and
    the read: the exception must not escape relink_folder and kill the CLI."""
    _seed(tmp_path, [files_md.Entry(path="src/a.py", branch="solved",
                                    ts="2026-08-04T06:41:07Z", reason="not-pushed")])

    def _raise(self, *args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", _raise)

    summary = relink_open_files.relink_folder(tmp_path)

    assert summary == {"repos": 0, "entries": 0, "linked_branch": 0,
                       "linked_default": 0, "adopted_dominant": 0, "unlinked": 0, "skipped": 0}


def test_relink_leaves_unknown_entries_untouched_and_counts_skipped(tmp_path, monkeypatch, tz_bucharest):
    """The core Important-3 reproduction: get_repo_info succeeds (so the repo
    is reachable) but the tree/blob probes for one entry fail transiently.
    That must not degrade an already-working link, and must not silently
    vanish from the summary either."""
    _seed(tmp_path, [files_md.Entry(
        path="src/a.py", branch="solved", ts="2026-08-04T06:41:07Z",
        blob_url="https://github.com/owner/repo/blob/solved/src/a.py", ref="branch")])
    monkeypatch.setattr(github_client, "get_repo_info",
                        lambda o, r: github_client.RepoInfo(default_branch="master"))
    monkeypatch.setattr(github_client, "get_repo_tree",
                        lambda o, r, b: github_client.UNKNOWN)
    monkeypatch.setattr(github_client, "head_blob",
                        lambda o, r, b, p: github_client.UNKNOWN)

    summary = relink_open_files.relink_folder(tmp_path)

    text = (tmp_path / files_md.session_filename()).read_text()
    assert "blob/solved/src/a.py" in text  # untouched, not degraded
    assert "reason:unknown" not in text
    assert summary == {"repos": 1, "entries": 0, "linked_branch": 0,
                       "linked_default": 0, "adopted_dominant": 0, "unlinked": 0, "skipped": 1}


def test_relink_canonicalizes_a_non_canonical_stored_url(tmp_path, monkeypatch, tz_bucharest):
    """Minor 5: repo_obj.url comes from parsed markdown, not necessarily the
    exact output of _canonical_repo_url — relink must re-canonicalize before
    calling _owner_repo, whose documented invariant assumes that shape."""
    doc = files_md.Doc(repos=[files_md.Repo(
        url="https://github.com/owner/repo.git", name="repo",
        default_branch="master", branch="solved",
        entries=[files_md.Entry(path="src/a.py", branch="solved",
                                ts="2026-08-04T06:41:07Z", reason="not-pushed")])])
    (tmp_path / files_md.session_filename()).write_text(doc.render(), encoding="utf-8")
    monkeypatch.setattr(github_client, "get_repo_info",
                        lambda o, r: github_client.RepoInfo(default_branch="master"))
    monkeypatch.setattr(github_client, "get_repo_tree",
                        lambda o, r, b: _tree("src/a.py") if b == "solved" else _tree())

    summary = relink_open_files.relink_folder(tmp_path)

    assert summary["repos"] == 1
    assert summary["linked_branch"] == 1


def test_relink_skips_non_canonical_repo_url(tmp_path, monkeypatch, tz_bucharest):
    doc = files_md.Doc(repos=[files_md.Repo(
        url="https://gitlab.com/owner/repo", name="repo",
        default_branch="master", branch="master",
        entries=[files_md.Entry(path="src/a.py", branch="master",
                                ts="2026-08-04T06:41:07Z", reason="not-pushed")])])
    (tmp_path / files_md.session_filename()).write_text(doc.render(), encoding="utf-8")
    with patch("daemon.github_client.get_repo_info") as info:
        summary = relink_open_files.relink_folder(tmp_path)
    info.assert_not_called()
    assert summary["repos"] == 0
    assert summary["skipped"] == 1


def test_cli_prints_json_summary(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "daemon.relink_open_files",
         "--session-folder", str(tmp_path)],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout)["entries"] == 0


def test_relink_moves_a_stray_main_file_onto_the_sessions_branch(tmp_path, monkeypatch,
                                                                 tz_bucharest):
    """The one file opened during a detour onto master, but present on the
    session's branch too, must end up linked on the session's branch — and stop
    advertising a branch chip the room never worked on."""
    _seed(tmp_path, [
        files_md.Entry(path="src/a.py", branch="solved", ts="2026-08-04T06:00:00Z",
                       blob_url="https://github.com/owner/repo/blob/solved/src/a.py",
                       ref="branch"),
        files_md.Entry(path="src/b.py", branch="solved", ts="2026-08-04T06:10:00Z",
                       blob_url="https://github.com/owner/repo/blob/solved/src/b.py",
                       ref="branch"),
        files_md.Entry(path="src/c.py", branch="master", ts="2026-08-04T07:00:00Z",
                       blob_url="https://github.com/owner/repo/blob/master/src/c.py",
                       ref="branch"),
    ])
    monkeypatch.setattr(github_client, "get_repo_info",
                        lambda o, r: github_client.RepoInfo(default_branch="master"))
    # Everything exists on both branches — the choice is purely about which one
    # the session lived on.
    monkeypatch.setattr(github_client, "get_repo_tree",
                        lambda o, r, b: _tree("src/a.py", "src/b.py", "src/c.py"))

    summary = relink_open_files.relink_folder(tmp_path)

    text = (tmp_path / files_md.session_filename()).read_text()
    assert "blob/master/" not in text
    assert "blob/solved/src/c.py" in text
    assert "· branch `" not in text          # the stray chip is gone
    assert summary["adopted_dominant"] == 1


def test_relink_keeps_a_file_that_only_exists_on_its_own_branch(tmp_path, monkeypatch,
                                                                tz_bucharest):
    """Promotion is opt-in on presence: a file the session's branch does not
    carry stays where it is, chip and all."""
    _seed(tmp_path, [
        files_md.Entry(path="src/a.py", branch="solved", ts="2026-08-04T06:00:00Z",
                       blob_url="https://github.com/owner/repo/blob/solved/src/a.py",
                       ref="branch"),
        files_md.Entry(path="src/b.py", branch="solved", ts="2026-08-04T06:10:00Z",
                       blob_url="https://github.com/owner/repo/blob/solved/src/b.py",
                       ref="branch"),
        files_md.Entry(path="only-on-master.py", branch="master",
                       ts="2026-08-04T07:00:00Z", reason="not-pushed"),
    ])
    monkeypatch.setattr(github_client, "get_repo_info",
                        lambda o, r: github_client.RepoInfo(default_branch="master"))
    monkeypatch.setattr(
        github_client, "get_repo_tree",
        lambda o, r, b: _tree("src/a.py", "src/b.py") if b == "solved"
        else _tree("only-on-master.py"))

    summary = relink_open_files.relink_folder(tmp_path)

    text = (tmp_path / files_md.session_filename()).read_text()
    assert "blob/master/only-on-master.py" in text
    assert "· branch `master`" in text
    assert summary["adopted_dominant"] == 0
