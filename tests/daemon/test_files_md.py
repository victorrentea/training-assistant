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


def test_render_linked_entry_with_no_ref_falls_back_to_default(tz_bucharest):
    """A migrated legacy entry can be linked (blob_url set) while carrying no
    `ref:` at all. Must not literally emit `ref:None` — that string parses
    back as the value "None", not as an absence."""
    doc = files_md.Doc(repos=[_repo_with([
        files_md.Entry(path="src/a.py", branch="master", ts="2026-08-04T06:41:07Z",
                       blob_url="https://github.com/owner/repo/blob/master/src/a.py",
                       ref=None),
    ])])
    rendered = doc.render()
    assert "ref:None" not in rendered
    assert "ref:default" in rendered


def test_render_skips_repo_with_no_entries_renders_empty_state():
    doc = files_md.Doc(repos=[files_md.Repo(
        url="https://github.com/owner/repo", name="repo",
        default_branch="main", branch="main", entries=[])])
    assert doc.render() == files_md.EMPTY_STATE


def test_render_skips_empty_repo_but_keeps_others(tz_bucharest):
    doc = files_md.Doc(repos=[
        files_md.Repo(url="https://github.com/owner/empty", name="empty",
                      default_branch="main", branch="main", entries=[]),
        _repo_with([files_md.Entry(
            path="src/a.py", branch="master", ts="2026-08-04T06:41:07Z",
            blob_url="https://github.com/owner/repo/blob/master/src/a.py", ref="branch")]),
    ])
    rendered = doc.render()
    assert "empty" not in rendered
    assert "[repo]" in rendered


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
    from daemon import github_client
    # `build_blob_url` percent-encodes the path, so this is the URL a space
    # actually produces — not an arbitrary hand-written shape.
    blob_url = github_client.build_blob_url("owner", "repo", "master", "src/my folder/a.py")
    assert blob_url == "https://github.com/owner/repo/blob/master/src/my%20folder/a.py"
    original = files_md.Doc(repos=[_repo_with([
        files_md.Entry(path="src/my folder/a.py", branch="master", ts="2026-08-04T06:41:07Z",
                       blob_url=blob_url, ref="branch"),
    ])])
    parsed = files_md.Doc.parse(original.render())
    assert parsed.repos[0].entries[0].path == "src/my folder/a.py"
    assert parsed.repos[0].entries[0].blob_url == blob_url


def test_parse_path_with_parens_roundtrips(tz_bucharest):
    """Before build_blob_url percent-encoded the path, `(`/`)` in it would
    truncate the URL at the first `)` (the linked-entry href group stops
    there) — degrading the link on the very next save cycle."""
    from daemon import github_client
    blob_url = github_client.build_blob_url("owner", "repo", "master", "src/a(1).java")
    assert blob_url == "https://github.com/owner/repo/blob/master/src/a%281%29.java"
    original = files_md.Doc(repos=[_repo_with([
        files_md.Entry(path="src/a(1).java", branch="master", ts="2026-08-04T06:41:07Z",
                       blob_url=blob_url, ref="branch"),
    ])])
    parsed = files_md.Doc.parse(original.render())
    assert parsed.repos[0].entries[0].path == "src/a(1).java"
    assert parsed.repos[0].entries[0].blob_url == blob_url


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
    # The tree probe itself is inconclusive (UNKNOWN, not a confirmed-absent
    # None) but the direct blob HEAD succeeds — that alone proves the ref usable.
    with patch.object(github_client, "get_repo_info", return_value=github_client.RepoInfo(default_branch="main")), \
         patch.object(github_client, "get_repo_tree", return_value=github_client.UNKNOWN), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened(
            "https://github.com/owner/repo.git",
            "main",
            "src/a.py",
        )
    text = (session_folder / "opened-files.md").read_text()
    assert "## [repo](https://github.com/owner/repo) — branch `main` <!-- branch:main default_branch:main -->" in text
    assert "- [src/a.py](https://github.com/owner/repo/blob/main/src/a.py)" in text
    assert "ts:2026-05-27T10:00:00Z" in text
    assert "ref:branch" in text


def test_record_public_repo_invalid_blob_writes_unlinked(session_folder, monkeypatch):
    _freeze_now(monkeypatch, "2026-05-27T10:01:00Z")
    with patch.object(github_client, "get_repo_info", return_value=github_client.RepoInfo(default_branch="main")), \
         patch.object(github_client, "get_repo_tree", return_value=None), \
         patch.object(github_client, "head_blob", return_value=False):
        files_md.record_file_opened(
            "https://github.com/owner/repo",
            "main",
            "src/missing.py",
        )
    text = (session_folder / "opened-files.md").read_text()
    # HEAD fails on the (only) ref tried, which is indistinguishable from a
    # missing branch — see _check_ref's docstring.
    assert "- src/missing.py" in text
    assert "ts:2026-05-27T10:01:00Z branch:main reason:no-branch" in text


def test_record_private_repo_writes_nothing(session_folder, monkeypatch):
    with patch.object(github_client, "get_repo_info", return_value=None):
        files_md.record_file_opened(
            "https://github.com/owner/private",
            "main",
            "src/a.py",
        )
    assert not (session_folder / "opened-files.md").exists()


def test_record_rate_limited_on_unknown_repo_drops_event(session_folder, monkeypatch):
    """Privacy rule: never list a repo we haven't verified as public."""
    with patch.object(github_client, "get_repo_info", return_value=github_client.RATE_LIMITED):
        files_md.record_file_opened(
            "https://github.com/owner/unknown",
            "main",
            "src/a.py",
        )
    assert not (session_folder / "opened-files.md").exists()


def test_record_rate_limited_on_known_public_repo_writes_unlinked(session_folder, monkeypatch):
    """If the repo is already in opened-files.md (= verified public earlier), a subsequent
    rate-limit still emits the entry — unlinked because we can't HEAD the blob."""
    _freeze_now(monkeypatch, "2026-05-27T09:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", return_value=github_client.UNKNOWN), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened("https://github.com/owner/repo", "main", "src/first.py")

    _freeze_now(monkeypatch, "2026-05-27T10:02:00Z")
    with patch.object(github_client, "get_repo_info", return_value=github_client.RATE_LIMITED):
        files_md.record_file_opened("https://github.com/owner/repo", "main", "src/second.py")
    text = (session_folder / "opened-files.md").read_text()
    assert "- [src/first.py](https://github.com/owner/repo/blob/main/src/first.py)" in text
    assert "- src/second.py" in text
    assert "ts:2026-05-27T10:02:00Z branch:main reason:rate-limited" in text


def test_record_rate_limited_reopen_preserves_an_existing_link(session_folder, monkeypatch):
    """A rate-limited re-open of an already-linked file must not clobber the
    working link — participants could click it a moment ago, and a
    mid-workshop rate limit must not take it away."""
    _freeze_now(monkeypatch, "2026-05-27T09:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", return_value=_tree("src/A.java")), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened("https://github.com/owner/repo", "master", "src/A.java")
    text_before = (session_folder / "opened-files.md").read_text()
    assert "- [src/A.java](https://github.com/owner/repo/blob/master/src/A.java)" in text_before
    assert "ref:branch" in text_before

    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    with patch.object(github_client, "get_repo_info", return_value=github_client.RATE_LIMITED):
        files_md.record_file_opened("https://github.com/owner/repo", "master", "src/A.java")

    text_after = (session_folder / "opened-files.md").read_text()
    assert "- [src/A.java](https://github.com/owner/repo/blob/master/src/A.java)" in text_after
    assert "ref:branch" in text_after
    assert "reason:rate-limited" not in text_after
    assert "ts:2026-05-27T10:00:00Z" in text_after  # recency still moves


def test_record_empty_path_drops_event(session_folder, monkeypatch):
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", return_value=None), \
         patch.object(github_client, "head_blob", return_value=True) as head:
        files_md.record_file_opened("https://github.com/owner/repo", "main", "")
    head.assert_not_called()
    assert not (session_folder / "opened-files.md").exists()


def test_record_non_github_host_dropped(session_folder, monkeypatch):
    with patch.object(github_client, "get_repo_info") as info:
        files_md.record_file_opened("https://gitlab.com/owner/repo", "main", "src/a.py")
    info.assert_not_called()
    assert not (session_folder / "opened-files.md").exists()


def test_repo_url_canonicalisation(session_folder, monkeypatch):
    """Trailing .git and trailing / both removed before storing."""
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", return_value=None), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened("https://github.com/owner/repo.git/", "main", "src/a.py")
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
    """The legacy `git_repos[]` record carries its own `branch`; migration
    must read it through rather than pass "" and silently fall back to the
    default branch — that was the exact bug this whole feature exists to fix."""
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
         patch.object(github_client, "get_repo_tree",
                       lambda o, r, b: _tree("src/a.py", "src/b.py") if b == "feature/x" else _tree()), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.migrate_session_if_needed(session_folder)

    md = (session_folder / "opened-files.md").read_text()
    assert "## [repo](https://github.com/owner/repo) — branch `feature/x` <!-- branch:feature/x default_branch:main -->" in md
    assert "[src/a.py]" in md and "[src/b.py]" in md
    assert "blob/feature/x/src/a.py" in md

    js = json.loads((session_folder / "session-state.json").read_text())
    assert "git_repos" not in js


def test_migration_defaults_branch_when_record_has_none(session_folder, monkeypatch):
    """A legacy record with no `branch` key at all (older than even the
    old feature) must still migrate — falling back to the default branch,
    not crash on a missing key."""
    _write_session_json(session_folder, {
        "git_repos": [
            {"url": "https://github.com/owner/repo", "files": ["src/a.py"], "file_urls": {}},
        ],
    })
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", lambda o, r, b: _tree("src/a.py")), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.migrate_session_if_needed(session_folder)

    md = (session_folder / "opened-files.md").read_text()
    assert "branch `main`" in md
    assert "blob/main/src/a.py" in md


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
# Branch-aware resolution tests
# ---------------------------------------------------------------------------

def _tree(*paths):
    return github_client.RepoTree(
        paths=frozenset(paths),
        truncated=False,
    )


def test_record_links_on_captured_branch(session_folder, monkeypatch, tz_bucharest):
    _freeze_now(monkeypatch, "2026-08-04T06:41:07Z")
    monkeypatch.setattr(github_client, "get_repo_info",
                        lambda o, r: github_client.RepoInfo(default_branch="master"))
    monkeypatch.setattr(github_client, "get_repo_tree",
                        lambda o, r, b: _tree("src/a.py") if b == "solved" else _tree())
    files_md.record_file_opened("https://github.com/owner/repo", "solved", "src/a.py")

    text = (session_folder / "opened-files.md").read_text()
    assert "blob/solved/src/a.py" in text
    assert "ref:branch" in text
    assert "branch:solved" in text
    # The repo heading follows the most recent open.
    assert "— branch `solved`" in text


def test_record_falls_back_to_default_branch(session_folder, monkeypatch, tz_bucharest):
    _freeze_now(monkeypatch, "2026-08-04T06:41:07Z")
    monkeypatch.setattr(github_client, "get_repo_info",
                        lambda o, r: github_client.RepoInfo(default_branch="master"))
    # The captured branch exists but does not carry the file; master does.
    monkeypatch.setattr(github_client, "get_repo_tree",
                        lambda o, r, b: _tree("src/a.py") if b == "master" else _tree("other.py"))
    files_md.record_file_opened("https://github.com/owner/repo", "wip", "src/a.py")

    text = (session_folder / "opened-files.md").read_text()
    assert "blob/master/src/a.py" in text
    assert "ref:default" in text


def test_record_unlinked_when_on_neither_ref(session_folder, monkeypatch, tz_bucharest):
    _freeze_now(monkeypatch, "2026-08-04T06:41:07Z")
    monkeypatch.setattr(github_client, "get_repo_info",
                        lambda o, r: github_client.RepoInfo(default_branch="master"))
    monkeypatch.setattr(github_client, "get_repo_tree", lambda o, r, b: _tree("other.py"))
    files_md.record_file_opened("https://github.com/owner/repo", "wip", "src/new.py")

    text = (session_folder / "opened-files.md").read_text()
    assert "reason:not-pushed" in text
    assert "](" not in text.split("\n")[-2]


def test_record_missing_branch_reports_no_branch(session_folder, monkeypatch, tz_bucharest):
    _freeze_now(monkeypatch, "2026-08-04T06:41:07Z")
    monkeypatch.setattr(github_client, "get_repo_info",
                        lambda o, r: github_client.RepoInfo(default_branch="master"))
    # get_repo_tree returns None for a branch GitHub does not have.
    monkeypatch.setattr(github_client, "get_repo_tree",
                        lambda o, r, b: _tree("other.py") if b == "master" else None)
    monkeypatch.setattr(github_client, "head_blob", lambda o, r, b, p: False)
    files_md.record_file_opened("https://github.com/owner/repo", "never-pushed", "src/new.py")

    assert "reason:no-branch" in (session_folder / "opened-files.md").read_text()


# ---------------------------------------------------------------------------
# Transient-failure ("unknown") handling — a network blip or a GitHub 5xx must
# never be reported, or acted on, as a definitive "not there".
# ---------------------------------------------------------------------------

def test_resolve_entry_reason_is_unknown_on_transient_failure(monkeypatch):
    """Both probes fail transiently (network blip / 5xx) — must resolve to
    "unknown", not silently degrade to "no-branch" or "not-pushed"."""
    monkeypatch.setattr(github_client, "get_repo_tree",
                        lambda o, r, b: github_client.UNKNOWN)
    monkeypatch.setattr(github_client, "head_blob",
                        lambda o, r, b, p: github_client.UNKNOWN)
    result = files_md.resolve_entry("owner", "repo", "solved", "master", "src/a.py")
    assert result == (None, None, "unknown")


def test_resolve_entry_links_normally_when_probes_are_definitive(monkeypatch):
    """Sanity check: a definitive tree hit still links exactly as before —
    the tri-state change must not regress the happy path."""
    monkeypatch.setattr(github_client, "get_repo_tree", lambda o, r, b: _tree("src/a.py"))
    result = files_md.resolve_entry("owner", "repo", "solved", "master", "src/a.py")
    assert result == (
        "https://github.com/owner/repo/blob/solved/src/a.py", "branch", None)


def test_record_new_entry_with_transient_failure_is_recorded_unlinked_unknown(
        session_folder, monkeypatch):
    """A brand-new entry has nothing to preserve, so an inconclusive probe
    still gets recorded — unlinked, tagged "unknown" rather than a guess."""
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", return_value=github_client.UNKNOWN), \
         patch.object(github_client, "head_blob", return_value=github_client.UNKNOWN):
        files_md.record_file_opened("https://github.com/owner/repo", "main", "src/a.py")
    text = (session_folder / "opened-files.md").read_text()
    assert "- src/a.py" in text
    assert "reason:unknown" in text
    assert "](" not in text.split("\n")[-2]


def test_record_transient_failure_after_working_link_preserves_it(session_folder, monkeypatch):
    """Reproduces the core bug: a network blip / GitHub 5xx arriving on a
    re-open of an already-linked file must not wipe the link — the summarizer
    runs a full relink as its first step, so this exact path is how one bad
    moment could strip every link in a repo."""
    _freeze_now(monkeypatch, "2026-05-27T09:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", return_value=_tree("src/A.java")), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened("https://github.com/owner/repo", "master", "src/A.java")

    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "get_repo_tree", return_value=github_client.UNKNOWN), \
         patch.object(github_client, "head_blob", return_value=github_client.UNKNOWN):
        files_md.record_file_opened("https://github.com/owner/repo", "master", "src/A.java")

    text = (session_folder / "opened-files.md").read_text()
    assert "- [src/A.java](https://github.com/owner/repo/blob/master/src/A.java)" in text
    assert "ref:branch" in text
    assert "ts:2026-05-27T10:00:00Z" in text  # recency still moves
    assert "reason:unknown" not in text


def test_record_same_path_twice_updates_time_and_branch(session_folder, monkeypatch, tz_bucharest):
    monkeypatch.setattr(github_client, "get_repo_info",
                        lambda o, r: github_client.RepoInfo(default_branch="master"))
    monkeypatch.setattr(github_client, "get_repo_tree", lambda o, r, b: _tree("src/a.py"))

    _freeze_now(monkeypatch, "2026-08-04T06:41:07Z")
    files_md.record_file_opened("https://github.com/owner/repo", "master", "src/a.py")
    _freeze_now(monkeypatch, "2026-08-04T08:20:31Z")
    files_md.record_file_opened("https://github.com/owner/repo", "solved", "src/a.py")

    text = (session_folder / "opened-files.md").read_text()
    assert text.count("- [src/a.py]") == 1          # one row, not two
    assert "ts:2026-08-04T08:20:31Z" in text        # the later open wins
    assert "ts:2026-08-04T06:41:07Z" not in text
    assert "blob/solved/" in text


def test_record_two_paths_sharing_a_basename_both_survive(session_folder, monkeypatch, tz_bucharest):
    """The old code collapsed these into one 'ambiguous' entry."""
    _freeze_now(monkeypatch, "2026-08-04T06:41:07Z")
    monkeypatch.setattr(github_client, "get_repo_info",
                        lambda o, r: github_client.RepoInfo(default_branch="master"))
    monkeypatch.setattr(github_client, "get_repo_tree",
                        lambda o, r, b: _tree("src/main/A.java", "src/test/A.java"))
    files_md.record_file_opened("https://github.com/owner/repo", "master", "src/main/A.java")
    files_md.record_file_opened("https://github.com/owner/repo", "master", "src/test/A.java")

    text = (session_folder / "opened-files.md").read_text()
    assert "src/main/A.java" in text and "src/test/A.java" in text
    assert "ambiguous" not in text


def test_record_empty_branch_resolves_on_default(session_folder, monkeypatch, tz_bucharest):
    _freeze_now(monkeypatch, "2026-08-04T06:41:07Z")
    monkeypatch.setattr(github_client, "get_repo_info",
                        lambda o, r: github_client.RepoInfo(default_branch="master"))
    monkeypatch.setattr(github_client, "get_repo_tree", lambda o, r, b: _tree("src/a.py"))
    files_md.record_file_opened("https://github.com/owner/repo", "", "src/a.py")

    text = (session_folder / "opened-files.md").read_text()
    assert "branch:master" in text
    assert "blob/master/src/a.py" in text


import os
import time as _time


@pytest.fixture
def tz_bucharest():
    """Pin the process timezone so local-time rendering is deterministic.

    Restores TZ (and calls tzset()) itself rather than going through
    monkeypatch: monkeypatch's implicit undo runs after this fixture's own
    teardown, so if it were the one restoring TZ, the final tzset() call
    here would run before that later, silent restore — leaving the C
    library's local-time state one step stale for whatever test runs next
    on a machine that had TZ set in the ambient environment.
    """
    original_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Bucharest"
    _time.tzset()
    yield
    if original_tz is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original_tz
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
