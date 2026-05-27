from pathlib import Path
from daemon import files_md


def test_empty_state_content():
    assert files_md.EMPTY_STATE == "# Files opened this session\n\nNo files opened yet\n"


def test_render_empty_doc():
    doc = files_md.Doc(repos=[])
    assert doc.render() == files_md.EMPTY_STATE


def test_render_single_repo_linked():
    doc = files_md.Doc(repos=[
        files_md.Repo(
            url="https://github.com/owner/repo",
            name="repo",
            default_branch="main",
            entries=[
                files_md.Entry(
                    basename="a.py",
                    blob_url="https://github.com/owner/repo/blob/main/src/a.py",
                    path="src/a.py",
                    ts="2026-05-27T10:00:00Z",
                    reason=None,
                ),
            ],
        ),
    ])
    expected = (
        "# Files opened this session\n\n"
        "## [repo](https://github.com/owner/repo) <!-- default_branch:main -->\n\n"
        "- [a.py](https://github.com/owner/repo/blob/main/src/a.py)"
        " <!-- ts:2026-05-27T10:00:00Z path:src/a.py -->\n"
    )
    assert doc.render() == expected


def test_render_single_repo_unlinked():
    doc = files_md.Doc(repos=[
        files_md.Repo(
            url="https://github.com/owner/repo",
            name="repo",
            default_branch="main",
            entries=[
                files_md.Entry(
                    basename="x.py",
                    blob_url=None,
                    path=None,
                    ts="2026-05-27T10:01:00Z",
                    reason="blob-404",
                ),
            ],
        ),
    ])
    expected = (
        "# Files opened this session\n\n"
        "## [repo](https://github.com/owner/repo) <!-- default_branch:main -->\n\n"
        "- x.py <!-- ts:2026-05-27T10:01:00Z reason:blob-404 -->\n"
    )
    assert doc.render() == expected


def test_parse_roundtrip(tmp_path: Path):
    original = files_md.Doc(repos=[
        files_md.Repo(
            url="https://github.com/owner/repo",
            name="repo",
            default_branch="main",
            entries=[
                files_md.Entry(
                    basename="a.py",
                    blob_url="https://github.com/owner/repo/blob/main/src/a.py",
                    path="src/a.py",
                    ts="2026-05-27T10:00:00Z",
                    reason=None,
                ),
                files_md.Entry(
                    basename="x.py",
                    blob_url=None,
                    path=None,
                    ts="2026-05-27T10:01:00Z",
                    reason="blob-404",
                ),
            ],
        ),
    ])
    rendered = original.render()
    parsed = files_md.Doc.parse(rendered)
    assert parsed.render() == rendered


def test_parse_empty_returns_empty_doc():
    assert files_md.Doc.parse("").repos == []
    assert files_md.Doc.parse(files_md.EMPTY_STATE).repos == []


def test_atomic_write_creates_tmp_then_renames(tmp_path: Path, monkeypatch):
    target = tmp_path / "files.md"
    seen: list[str] = []
    real_replace = __import__("os").replace

    def spy_replace(src, dst):
        seen.append(f"replace {Path(src).name} -> {Path(dst).name}")
        real_replace(src, dst)

    monkeypatch.setattr("os.replace", spy_replace)
    files_md.atomic_write(target, "hello\n")
    assert target.read_text() == "hello\n"
    assert any("replace files.md.tmp -> files.md" in s for s in seen)


import datetime as _dt
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
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened(
            url="https://github.com/owner/repo.git",
            file_path="src/a.py",
        )
    text = (session_folder / "files.md").read_text()
    assert "## [repo](https://github.com/owner/repo) <!-- default_branch:main -->" in text
    assert "- [a.py](https://github.com/owner/repo/blob/main/src/a.py)" in text
    assert "ts:2026-05-27T10:00:00Z" in text
    assert "path:src/a.py" in text


def test_record_public_repo_invalid_blob_writes_unlinked(session_folder, monkeypatch):
    _freeze_now(monkeypatch, "2026-05-27T10:01:00Z")
    with patch.object(github_client, "get_repo_info", return_value=github_client.RepoInfo(default_branch="main")), \
         patch.object(github_client, "head_blob", return_value=False):
        files_md.record_file_opened(
            url="https://github.com/owner/repo",
            file_path="src/missing.py",
        )
    text = (session_folder / "files.md").read_text()
    assert "- missing.py <!-- ts:2026-05-27T10:01:00Z reason:blob-404 -->" in text


def test_record_private_repo_writes_nothing(session_folder, monkeypatch):
    with patch.object(github_client, "get_repo_info", return_value=None):
        files_md.record_file_opened(
            url="https://github.com/owner/private",
            file_path="src/a.py",
        )
    assert not (session_folder / "files.md").exists()


def test_record_rate_limited_on_unknown_repo_drops_event(session_folder, monkeypatch):
    """Privacy rule: never list a repo we haven't verified as public."""
    with patch.object(github_client, "get_repo_info", return_value=github_client.RATE_LIMITED):
        files_md.record_file_opened(
            url="https://github.com/owner/unknown",
            file_path="src/a.py",
        )
    assert not (session_folder / "files.md").exists()


def test_record_rate_limited_on_known_public_repo_writes_unlinked(session_folder, monkeypatch):
    """If the repo is already in files.md (= verified public earlier), a subsequent
    rate-limit still emits the entry — unlinked because we can't HEAD the blob."""
    _freeze_now(monkeypatch, "2026-05-27T09:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened("https://github.com/owner/repo", "src/first.py")

    _freeze_now(monkeypatch, "2026-05-27T10:02:00Z")
    with patch.object(github_client, "get_repo_info", return_value=github_client.RATE_LIMITED):
        files_md.record_file_opened("https://github.com/owner/repo", "src/second.py")
    text = (session_folder / "files.md").read_text()
    assert "- [first.py](https://github.com/owner/repo/blob/main/src/first.py)" in text
    assert "- second.py <!-- ts:2026-05-27T10:02:00Z reason:rate-limited -->" in text


def test_record_dedup_same_basename_skips(session_folder, monkeypatch):
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened("https://github.com/owner/repo", "src/a.py")
        _freeze_now(monkeypatch, "2026-05-27T10:05:00Z")
        files_md.record_file_opened("https://github.com/owner/repo", "src/a.py")
    text = (session_folder / "files.md").read_text()
    assert text.count("- [a.py]") == 1
    assert "ts:2026-05-27T10:00:00Z" in text
    assert "ts:2026-05-27T10:05:00Z" not in text


def test_record_collision_downgrades_to_unlinked(session_folder, monkeypatch):
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened("https://github.com/owner/repo", "src/foo/utils.py")
        _freeze_now(monkeypatch, "2026-05-27T10:05:00Z")
        files_md.record_file_opened("https://github.com/owner/repo", "src/bar/utils.py")
    text = (session_folder / "files.md").read_text()
    assert text.count("utils.py") == 1
    assert "- utils.py <!-- ts:2026-05-27T10:00:00Z reason:ambiguous -->" in text
    assert "[utils.py]" not in text  # link stripped


def test_record_empty_path_drops_event(session_folder, monkeypatch):
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "head_blob", return_value=True) as head:
        files_md.record_file_opened("https://github.com/owner/repo", "")
    head.assert_not_called()
    assert not (session_folder / "files.md").exists()


def test_record_non_github_host_dropped(session_folder, monkeypatch):
    with patch.object(github_client, "get_repo_info") as info:
        files_md.record_file_opened("https://gitlab.com/owner/repo", "src/a.py")
    info.assert_not_called()
    assert not (session_folder / "files.md").exists()


def test_repo_url_canonicalisation(session_folder, monkeypatch):
    """Trailing .git and trailing / both removed before storing."""
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened("https://github.com/owner/repo.git/", "src/a.py")
    text = (session_folder / "files.md").read_text()
    assert "https://github.com/owner/repo)" in text  # canonical form
    assert ".git" not in text


def test_sanitize_for_wire_strips_html_comments():
    md = (
        "# Files opened this session\n\n"
        "## [repo](https://github.com/owner/repo) <!-- default_branch:main -->\n\n"
        "- [a.py](https://github.com/owner/repo/blob/main/src/a.py) <!-- ts:X path:src/a.py -->\n"
    )
    out = files_md.sanitize_for_wire(md)
    assert "<!--" not in out
    assert "## [repo](https://github.com/owner/repo)" in out
    assert "- [a.py](https://github.com/owner/repo/blob/main/src/a.py)" in out
