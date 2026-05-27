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
