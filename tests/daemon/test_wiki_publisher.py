import os
import threading
from pathlib import Path

import pytest

from daemon.wiki import builder
from daemon.wiki.publisher import POLL_INTERVAL_S, SETTLE_S, WikiPublisher, session_title


class Clock:
    def __init__(self, now: float):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _page(folder: Path, name: str, text: str, mtime: float) -> None:
    path = folder / "wiki" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (mtime, mtime))


class Harness:
    """A publisher whose build/upload are recorded, run synchronously."""

    def __init__(self, tmp_path: Path):
        self.folder = tmp_path / "2026-09-25 AI@Rabo"
        self.folder.mkdir()
        self.clock = Clock(1_000_000.0)
        self.builds: list[str] = []
        self.uploads: list[tuple[str, bytes]] = []
        self.changes: list[str | None] = []
        self.fail_build = False
        self.publisher = WikiPublisher(
            upload=lambda sid, payload: self.uploads.append((sid, payload)),
            on_change=self.changes.append,
            build=self._build,
            clock=self.clock,
        )

    def _build(self, wiki_dir: Path, title: str) -> bytes:
        if self.fail_build:
            raise builder.WikiBuildError("boom")
        self.builds.append(title)
        return f"site-{len(self.builds)}".encode()

    def tick(self, session_id="e2etst", folder=None):
        self.clock.advance(POLL_INTERVAL_S)
        self.publisher.tick(session_id, folder or self.folder)

    def page(self, name="Home.md", text="# Home", age=SETTLE_S + 1):
        _page(self.folder, name, text, self.clock.now - age)


@pytest.fixture
def h(tmp_path, monkeypatch):
    # Run the build thread inline so assertions see its effects immediately.
    class _Inline:
        def __init__(self, target, args, **_):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(threading, "Thread", _Inline)
    return Harness(tmp_path)


def test_no_wiki_folder_publishes_nothing(h):
    h.tick()
    assert h.builds == [] and h.changes == []


def test_settled_wiki_is_built_uploaded_and_announced(h):
    h.page()
    h.tick()
    assert h.builds == ["AI@Rabo"]
    assert h.uploads == [("e2etst", b"site-1")]
    assert len(h.changes) == 1 and h.changes[0] is not None
    assert h.publisher.updated_at == h.changes[0]


def test_waits_while_the_summarizer_is_still_writing(h):
    h.page(age=1)
    h.tick()
    assert h.builds == []
    h.clock.advance(SETTLE_S)
    h.tick()
    assert h.builds == ["AI@Rabo"]


def test_unchanged_wiki_is_not_rebuilt(h):
    h.page()
    for _ in range(5):
        h.tick()
    assert len(h.builds) == 1


def test_edited_wiki_is_rebuilt(h):
    h.page()
    h.tick()
    h.page("Chat Memory.md", "# Chat memory")
    h.tick()
    assert len(h.builds) == 2
    assert len(h.changes) == 2


def test_polls_at_most_every_interval(h, monkeypatch):
    calls = []
    monkeypatch.setattr("daemon.wiki.publisher.fingerprint", lambda d: calls.append(d))
    h.page()
    h.tick()
    h.publisher.tick("e2etst", h.folder)  # same instant: skipped
    assert len(calls) == 1


def test_reconnect_resends_the_cached_site_without_rebuilding(h):
    h.page()
    h.tick()
    h.publisher.invalidate()
    h.tick()
    assert len(h.builds) == 1
    assert h.uploads == [("e2etst", b"site-1"), ("e2etst", b"site-1")]


def test_reconnect_before_any_publish_is_a_no_op(h):
    h.publisher.invalidate()
    h.tick()
    assert h.uploads == []


def test_new_session_hides_the_old_wiki_until_its_own_is_built(h, tmp_path):
    h.page()
    h.tick()
    other = tmp_path / "2026-09-26 Other"
    other.mkdir()
    h.tick(session_id="newses", folder=other)
    assert h.changes[-1] is None
    assert h.publisher.updated_at is None
    assert h.uploads[-1][0] == "e2etst"  # nothing uploaded for the new session


def test_deleted_wiki_is_withdrawn(h):
    h.page()
    h.tick()
    (h.folder / "wiki" / "Home.md").unlink()
    h.tick()
    assert h.changes[-1] is None


def test_failed_build_is_not_retried_in_a_loop(h):
    h.fail_build = True
    h.page()
    h.tick()
    h.fail_build = False
    h.tick()
    assert h.builds == []  # same content, still inside the back-off
    assert h.changes == []


def test_obsidian_settings_do_not_count_as_content(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "workspace.md").write_text("x")
    assert builder.fingerprint(tmp_path) is None
    (tmp_path / "Home.md").write_text("# Home")
    assert builder.fingerprint(tmp_path)[0] == 1


def test_home_page_becomes_the_landing_page(tmp_path):
    wiki_dir, out = tmp_path / "wiki", tmp_path / "out"
    wiki_dir.mkdir()
    out.mkdir()
    (out / "Home.html").write_text("home")
    builder._use_home_as_landing_page(wiki_dir, out)
    assert (out / "index.html").read_text() == "home"


def test_explicit_index_is_left_alone(tmp_path):
    wiki_dir, out = tmp_path / "wiki", tmp_path / "out"
    wiki_dir.mkdir()
    out.mkdir()
    (wiki_dir / "index.md").write_text("# Index")
    (out / "index.html").write_text("index")
    (out / "Home.html").write_text("home")
    builder._use_home_as_landing_page(wiki_dir, out)
    assert (out / "index.html").read_text() == "index"


def test_missing_quartz_install_says_how_to_fix_it(tmp_path, monkeypatch):
    monkeypatch.setenv("QUARTZ_DIR", str(tmp_path / "nowhere"))
    with pytest.raises(builder.WikiBuildError, match="setup-quartz.sh"):
        builder.build_site(tmp_path, "t", tmp_path / "out")


@pytest.mark.parametrize(
    "folder, title",
    [("2026-09-25 AI@Rabo", "AI@Rabo"), ("2026-09-21..23 Arch@DB", "Arch@DB"), ("e2e-test", "e2e-test")],
)
def test_session_title_drops_the_date(folder, title):
    assert session_title(Path(folder)) == title
