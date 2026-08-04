import json
from pathlib import Path
from daemon import files_md


def test_empty_state_content():
    assert files_md.EMPTY_STATE == "# Files opened this session\n\nNo files opened yet\n"


def test_render_empty_doc():
    doc = files_md.Doc(repos=[])
    assert doc.render() == files_md.EMPTY_STATE


def _repo_with(entries, branch="master"):
    return files_md.Repo(
        url="https://github.com/owner/repo",
        name="repo",
        default_branch="master",
        branch=branch,
        entries=entries,
    )


def test_render_linked_entry_on_repo_branch(tz_bucharest):
    doc = files_md.Doc(repos=[_repo_with([
        files_md.Entry(
            path="src/a.py",
            branch="master",
            ts="2026-08-04T06:41:07Z",
            blob_url="https://github.com/owner/repo/blob/master/src/a.py",
            ref="branch",
        ),
    ])])
    assert doc.render() == (
        "# Files opened this session\n\n"
        "## [repo](https://github.com/owner/repo) — branch `master` "
        "<!-- branch:master default_branch:master -->\n\n"
        "- [src/a.py](https://github.com/owner/repo/blob/master/src/a.py) — 09:41 "
        "<!-- ts:2026-08-04T06:41:07Z branch:master ref:branch -->\n"
    )


def test_render_entry_on_divergent_branch_shows_visible_chip(tz_bucharest):
    doc = files_md.Doc(repos=[_repo_with([
        files_md.Entry(
            path="src/b.py",
            branch="solved",
            ts="2026-08-04T07:05:12Z",
            blob_url="https://github.com/owner/repo/blob/solved/src/b.py",
            ref="branch",
        ),
    ])])
    # The chip must be in the VISIBLE text: sanitize_for_wire strips comments
    # before participants ever see the document.
    assert "— 10:05 · branch `solved`" in doc.render()
    assert "· branch" in files_md.sanitize_for_wire(doc.render())


def test_render_unlinked_entry_has_no_link(tz_bucharest):
    doc = files_md.Doc(repos=[_repo_with([
        files_md.Entry(path="src/c.py", branch="master", ts="2026-08-04T08:20:31Z",
                       reason="not-pushed"),
    ])])
    rendered = doc.render()
    assert "- src/c.py — 11:20 <!-- ts:2026-08-04T08:20:31Z branch:master reason:not-pushed -->" in rendered
    assert "](" not in rendered.split("\n")[-2]


def test_render_switches_all_entries_to_dated_when_days_differ(tz_bucharest):
    doc = files_md.Doc(repos=[_repo_with([
        files_md.Entry(path="src/a.py", branch="master", ts="2026-08-04T06:41:07Z",
                       blob_url="https://github.com/owner/repo/blob/master/src/a.py", ref="branch"),
        files_md.Entry(path="src/b.py", branch="master", ts="2026-08-05T06:41:07Z",
                       blob_url="https://github.com/owner/repo/blob/master/src/b.py", ref="branch"),
    ])])
    rendered = doc.render()
    assert "— Aug 4 09:41 " in rendered
    assert "— Aug 5 09:41 " in rendered
    assert "— 09:41 " not in rendered


def test_parse_roundtrip(tz_bucharest):
    original = files_md.Doc(repos=[_repo_with([
        files_md.Entry(path="src/a.py", branch="master", ts="2026-08-04T06:41:07Z",
                       blob_url="https://github.com/owner/repo/blob/master/src/a.py", ref="branch"),
        files_md.Entry(path="src/b.py", branch="solved", ts="2026-08-04T07:05:12Z",
                       blob_url="https://github.com/owner/repo/blob/solved/src/b.py", ref="branch"),
        files_md.Entry(path="src/c.py", branch="master", ts="2026-08-04T08:20:31Z",
                       reason="not-pushed"),
    ])])
    rendered = original.render()
    parsed = files_md.Doc.parse(rendered)
    assert parsed.render() == rendered
    assert [e.path for e in parsed.repos[0].entries] == ["src/a.py", "src/b.py", "src/c.py"]
    assert parsed.repos[0].entries[1].branch == "solved"
    assert parsed.repos[0].branch == "master"


def test_parse_path_with_spaces_roundtrips(tz_bucharest):
    original = files_md.Doc(repos=[_repo_with([
        files_md.Entry(path="src/my folder/a.py", branch="master", ts="2026-08-04T06:41:07Z",
                       blob_url="https://github.com/owner/repo/blob/master/src/my%20folder/a.py",
                       ref="branch"),
    ])])
    parsed = files_md.Doc.parse(original.render())
    assert parsed.repos[0].entries[0].path == "src/my folder/a.py"


def test_parse_old_format_linked_entry_uses_path_comment(tz_bucharest):
    old = (
        "# Files opened this session\n\n"
        "## [repo](https://github.com/owner/repo) <!-- default_branch:main -->\n\n"
        "- [a.py](https://github.com/owner/repo/blob/main/src/a.py) "
        "<!-- ts:2026-05-27T10:00:00Z path:src/a.py -->\n"
    )
    parsed = files_md.Doc.parse(old)
    assert len(parsed.repos) == 1
    assert parsed.repos[0].branch == "main"          # falls back to default_branch
    assert parsed.repos[0].entries[0].path == "src/a.py"
    assert parsed.repos[0].entries[0].branch == "main"


def test_parse_old_format_drops_entries_without_path():
    old = (
        "# Files opened this session\n\n"
        "## [repo](https://github.com/owner/repo) <!-- default_branch:main -->\n\n"
        "- x.py <!-- ts:2026-05-27T10:01:00Z reason:blob-404 -->\n"
    )
    parsed = files_md.Doc.parse(old)
    assert parsed.repos[0].entries == []


def test_parse_unlinked_file_at_repo_root_survives(tz_bucharest):
    """A root-level unlinked file has no "/" in its path — it must not be
    mistaken for a legacy basename-only entry and dropped."""
    original = files_md.Doc(repos=[_repo_with([
        files_md.Entry(path="README.md", branch="master", ts="2026-08-04T06:41:07Z",
                       reason="not-pushed"),
    ])])
    parsed = files_md.Doc.parse(original.render())
    assert [e.path for e in parsed.repos[0].entries] == ["README.md"]


def test_entry_basename_is_derived_from_path():
    e = files_md.Entry(path="src/deep/A.java", branch="master", ts="2026-08-04T06:41:07Z")
    assert e.basename == "A.java"


def test_parse_empty_returns_empty_doc():
    assert files_md.Doc.parse("").repos == []
    assert files_md.Doc.parse(files_md.EMPTY_STATE).repos == []


def test_count_open_files_none_and_missing(tmp_path: Path):
    assert files_md.count_open_files(None) == 0
    assert files_md.count_open_files(tmp_path) == 0  # no opened-files.md yet


def test_count_open_files_empty_state(tmp_path: Path):
    (tmp_path / "opened-files.md").write_text(files_md.EMPTY_STATE, encoding="utf-8")
    assert files_md.count_open_files(tmp_path) == 0


def test_count_open_files_counts_entries_across_repos(tmp_path: Path, tz_bucharest):
    doc = files_md.Doc(repos=[
        files_md.Repo(url="https://github.com/owner/repo", name="repo",
                      default_branch="main", branch="main", entries=[
                          files_md.Entry(path="src/a.py", branch="main", ts="2026-08-04T06:41:07Z",
                                         blob_url="https://github.com/owner/repo/blob/main/src/a.py",
                                         ref="branch"),
                          files_md.Entry(path="src/x.py", branch="main", ts="2026-08-04T06:42:07Z",
                                         reason="not-pushed"),
                      ]),
        files_md.Repo(url="https://github.com/owner/other", name="other",
                      default_branch="main", branch="main", entries=[
                          files_md.Entry(path="c.py", branch="main", ts="2026-08-04T06:43:07Z",
                                         blob_url="https://github.com/owner/other/blob/main/c.py",
                                         ref="branch"),
                      ]),
    ])
    (tmp_path / "opened-files.md").write_text(doc.render(), encoding="utf-8")
    assert files_md.count_open_files(tmp_path) == 3


def test_atomic_write_creates_tmp_then_renames(tmp_path: Path, monkeypatch):
    target = tmp_path / "opened-files.md"
    seen: list[str] = []
    real_replace = __import__("os").replace

    def spy_replace(src, dst):
        seen.append(f"replace {Path(src).name} -> {Path(dst).name}")
        real_replace(src, dst)

    monkeypatch.setattr("os.replace", spy_replace)
    files_md.atomic_write(target, "hello\n")
    assert target.read_text() == "hello\n"
    assert any("replace opened-files.md.tmp -> opened-files.md" in s for s in seen)


from unittest.mock import patch

import pytest

from daemon import github_client


@pytest.fixture
def session_folder(tmp_path: Path, monkeypatch):
    folder = tmp_path / "session1"
    folder.mkdir()
    monkeypatch.setattr(files_md, "_get_active_session_folder", lambda: folder)
    github_client.reset_cache()
    yield folder
    github_client.reset_cache()


def _freeze_now(monkeypatch, iso: str):
    monkeypatch.setattr(files_md, "_utcnow_iso", lambda: iso)


def test_record_unknown_repo_public_with_valid_blob(session_folder, monkeypatch):
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    with patch.object(github_client, "get_repo_info", return_value=github_client.RepoInfo(default_branch="main")), \
         patch.object(github_client, "get_repo_tree", return_value=None), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened(
            url="https://github.com/owner/repo.git",
            file_path="src/a.py",
        )
    text = (session_folder / "opened-files.md").read_text()
    assert "## [repo](https://github.com/owner/repo) <!-- default_branch:main -->" in text
    assert "- [src/a.py](https://github.com/owner/repo/blob/main/src/a.py)" in text
    assert "ts:2026-05-27T10:00:00Z" in text
    assert "path:src/a.py" in text


def test_record_public_repo_invalid_blob_writes_unlinked(session_folder, monkeypatch):
    _freeze_now(monkeypatch, "2026-05-27T10:01:00Z")
    with patch.object(github_client, "get_repo_info", return_value=github_client.RepoInfo(default_branch="main")), \
         patch.object(github_client, "get_repo_tree", return_value=None), \
         patch.object(github_client, "head_blob", return_value=False):
        files_md.record_file_opened(
            url="https://github.com/owner/repo",
            file_path="src/missing.py",
        )
    text = (session_folder / "opened-files.md").read_text()
    assert "- missing.py <!-- ts:2026-05-27T10:01:00Z reason:blob-404 -->" in text


def test_record_private_repo_writes_nothing(session_folder, monkeypatch):
    with patch.object(github_client, "get_repo_info", return_value=None):
        files_md.record_file_opened(
            url="https://github.com/owner/private",
            file_path="src/a.py",
        )
    assert not (session_folder / "opened-files.md").exists()


def test_record_rate_limited_on_unknown_repo_drops_event(session_folder, monkeypatch):
    """Privacy rule: never list a repo we haven't verified as public."""
    with patch.object(github_client, "get_repo_info", return_value=github_client.RATE_LIMITED):
        files_md.record_file_opened(
            url="https://github.com/owner/unknown",
            file_path="src/a.py",
        )
    assert not (session_folder / "opened-files.md").exists()


def test_record_rate_limited_on_known_public_repo_writes_unlinked(session_folder, monkeypatch):
    """If the repo is already in opened-files.md (= verified public earlier), a subsequent
    rate-limit still emits the entry — unlinked because we can't HEAD the blob."""
    _freeze_now(monkeypatch, "2026-05-27T09:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", return_value=None), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened("https://github.com/owner/repo", "src/first.py")

    _freeze_now(monkeypatch, "2026-05-27T10:02:00Z")
    with patch.object(github_client, "get_repo_info", return_value=github_client.RATE_LIMITED):
        files_md.record_file_opened("https://github.com/owner/repo", "src/second.py")
    text = (session_folder / "opened-files.md").read_text()
    assert "- [src/first.py](https://github.com/owner/repo/blob/main/src/first.py)" in text
    assert "- second.py <!-- ts:2026-05-27T10:02:00Z reason:rate-limited -->" in text


def test_record_empty_path_drops_event(session_folder, monkeypatch):
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", return_value=None), \
         patch.object(github_client, "head_blob", return_value=True) as head:
        files_md.record_file_opened("https://github.com/owner/repo", "")
    head.assert_not_called()
    assert not (session_folder / "opened-files.md").exists()


def test_record_non_github_host_dropped(session_folder, monkeypatch):
    with patch.object(github_client, "get_repo_info") as info:
        files_md.record_file_opened("https://gitlab.com/owner/repo", "src/a.py")
    info.assert_not_called()
    assert not (session_folder / "opened-files.md").exists()


def test_repo_url_canonicalisation(session_folder, monkeypatch):
    """Trailing .git and trailing / both removed before storing."""
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", return_value=None), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened("https://github.com/owner/repo.git/", "src/a.py")
    text = (session_folder / "opened-files.md").read_text()
    assert "https://github.com/owner/repo)" in text  # canonical form
    assert ".git" not in text


def test_sanitize_for_wire_strips_html_comments():
    md = (
        "# Files opened this session\n\n"
        "## [repo](https://github.com/owner/repo) <!-- default_branch:main -->\n\n"
        "- [src/a.py](https://github.com/owner/repo/blob/main/src/a.py) <!-- ts:X path:src/a.py -->\n"
    )
    out = files_md.sanitize_for_wire(md)
    assert "<!--" not in out
    assert "## [repo](https://github.com/owner/repo)" in out
    assert "- [src/a.py](https://github.com/owner/repo/blob/main/src/a.py)" in out


def _write_session_json(folder, payload):
    p = folder / "session-state.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_migration_converts_git_repos_and_strips_key(session_folder, monkeypatch):
    _write_session_json(session_folder, {
        "mode": "workshop",
        "git_repos": [
            {
                "url": "https://github.com/owner/repo",
                "branch": "feature/x",
                "files": ["src/a.py", "src/b.py"],
                "file_urls": {},
            },
        ],
    })
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", return_value=None), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.migrate_session_if_needed(session_folder)

    md = (session_folder / "opened-files.md").read_text()
    assert "## [repo](https://github.com/owner/repo) <!-- default_branch:main -->" in md
    assert "[src/a.py]" in md and "[src/b.py]" in md

    js = json.loads((session_folder / "session-state.json").read_text())
    assert "git_repos" not in js


def test_migration_idempotent_when_files_md_exists(session_folder, monkeypatch):
    (session_folder / "opened-files.md").write_text("# Files opened this session\n\nNo files opened yet\n")
    _write_session_json(session_folder, {"git_repos": [
        {"url": "https://github.com/owner/repo", "branch": "main", "files": ["src/a.py"], "file_urls": {}},
    ]})
    with patch.object(github_client, "get_repo_info") as info:
        files_md.migrate_session_if_needed(session_folder)
    info.assert_not_called()
    # session-state.json still untouched if opened-files.md was already present
    js = json.loads((session_folder / "session-state.json").read_text())
    assert "git_repos" in js


def test_migration_no_op_when_no_git_repos(session_folder, monkeypatch):
    _write_session_json(session_folder, {"mode": "workshop"})
    with patch.object(github_client, "get_repo_info") as info:
        files_md.migrate_session_if_needed(session_folder)
    info.assert_not_called()
    assert not (session_folder / "opened-files.md").exists()


# ---------------------------------------------------------------------------
# Tree-based resolution tests
# ---------------------------------------------------------------------------

def _tree(paths_by_basename: dict, truncated: bool = False) -> github_client.RepoTree:
    paths = []
    for plist in paths_by_basename.values():
        paths.extend(plist)
    return github_client.RepoTree(
        paths=frozenset(paths),
        paths_by_basename={k: list(v) for k, v in paths_by_basename.items()},
        truncated=truncated,
    )


def test_record_tree_resolves_basename_to_full_path(session_folder, monkeypatch):
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    tree = _tree({"packages.puml": ["petclinic-backend/docs/packages.puml"]})
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", return_value=tree):
        files_md.record_file_opened(
            "https://github.com/victorrentea/petclinic",
            "packages.puml",  # addon sent just basename
        )
    text = (session_folder / "opened-files.md").read_text()
    assert "- [petclinic-backend/docs/packages.puml](https://github.com/victorrentea/petclinic/blob/main/petclinic-backend/docs/packages.puml)" in text
    assert "path:petclinic-backend/docs/packages.puml" in text


def test_record_tree_no_match_writes_not_in_repo(session_folder, monkeypatch):
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    tree = _tree({"other.py": ["src/other.py"]})  # basename not present
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", return_value=tree):
        files_md.record_file_opened(
            "https://github.com/owner/repo",
            "missing.py",
        )
    text = (session_folder / "opened-files.md").read_text()
    assert "- missing.py <!-- ts:2026-05-27T10:00:00Z reason:not-in-repo -->" in text


def test_record_tree_multiple_matches_writes_ambiguous(session_folder, monkeypatch):
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    tree = _tree({"utils.py": ["src/foo/utils.py", "src/bar/utils.py"]})
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", return_value=tree):
        files_md.record_file_opened(
            "https://github.com/owner/repo",
            "utils.py",
        )
    text = (session_folder / "opened-files.md").read_text()
    assert "- utils.py <!-- ts:2026-05-27T10:00:00Z reason:ambiguous -->" in text


def test_record_tree_exact_path_match_preferred(session_folder, monkeypatch):
    """If the addon sends the full path AND it matches the tree, use it directly even if basename is ambiguous."""
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    tree = _tree({"a.py": ["src/foo/a.py", "src/bar/a.py"]})  # basename ambiguous
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", return_value=tree):
        files_md.record_file_opened(
            "https://github.com/owner/repo",
            "src/foo/a.py",  # exact path → unambiguous link
        )
    text = (session_folder / "opened-files.md").read_text()
    assert "[src/foo/a.py](https://github.com/owner/repo/blob/main/src/foo/a.py)" in text
    assert "path:src/foo/a.py" in text


def test_record_tree_truncated_falls_back_to_head(session_folder, monkeypatch):
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    tree = _tree({"x.py": ["x.py"]}, truncated=True)
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", return_value=tree), \
         patch.object(github_client, "head_blob", return_value=True) as head:
        files_md.record_file_opened(
            "https://github.com/owner/repo",
            "src/x.py",
        )
    head.assert_called_once()  # HEAD fallback used because tree truncated
    text = (session_folder / "opened-files.md").read_text()
    assert "[src/x.py]" in text
    assert "path:src/x.py" in text


import time as _time


@pytest.fixture
def tz_bucharest(monkeypatch):
    """Pin the process timezone so local-time rendering is deterministic."""
    monkeypatch.setenv("TZ", "Europe/Bucharest")
    _time.tzset()
    yield
    monkeypatch.delenv("TZ", raising=False)
    _time.tzset()


def test_to_local_converts_utc_to_configured_zone(tz_bucharest):
    # 06:41 UTC is 09:41 in Bucharest (UTC+3 in August).
    assert files_md._to_local("2026-08-04T06:41:07Z").hour == 9


def test_needs_date_false_for_single_local_day(tz_bucharest):
    assert files_md._needs_date(["2026-08-04T06:41:07Z", "2026-08-04T08:20:31Z"]) is False


def test_needs_date_true_across_local_days(tz_bucharest):
    assert files_md._needs_date(["2026-08-04T06:41:07Z", "2026-08-05T06:41:07Z"]) is True


def test_needs_date_uses_local_not_utc_calendar(tz_bucharest):
    # 22:30 UTC on the 4th is 01:30 local on the 5th — two local days, one UTC day.
    assert files_md._needs_date(["2026-08-04T07:00:00Z", "2026-08-04T22:30:00Z"]) is True


def test_needs_date_empty_list_is_false():
    assert files_md._needs_date([]) is False


def test_format_local_time_without_date(tz_bucharest):
    assert files_md.format_local_time("2026-08-04T06:41:07Z", False) == "09:41"


def test_format_local_time_with_date(tz_bucharest):
    assert files_md.format_local_time("2026-08-04T06:41:07Z", True) == "Aug 4 09:41"
