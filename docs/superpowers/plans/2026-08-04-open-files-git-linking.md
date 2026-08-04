# Open Files: Accurate Git Linking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every file link in the participant "Files" tab point at the exact path on the branch it was opened from, repair links for files that were not yet pushed when opened, and render the list as a folder tree.

**Architecture:** The IntelliJ plugin already reports the exact repo-relative path and current branch to the macOS addon, which forwards them to the daemon over the WS bridge. The daemon currently discards the branch and re-guesses the path by basename. This plan stops the discarding, keys entries by `(repo, path)`, resolves against the captured branch with a default-branch fallback, adds an explicit relink pass the summarizer invokes, and moves tree-building into the participant page as a pure, unit-testable function.

**Tech Stack:** Python 3.12 + FastAPI/Pydantic (daemon), vanilla JS in a single HTML file (participant page), Swift/SwiftPM (macOS addon), Kotlin/Gradle + IntelliJ Platform SDK (plugin), pytest, plain `node` for JS unit tests.

**Design spec:** `docs/superpowers/specs/2026-08-04-open-files-git-linking-design.md`

## Global Constraints

- All code, comments, variable names, commit messages and documentation in **English**.
- Push directly to `master` after each task; never open a PR, never push to `main`.
- Daemon logging follows `daemon/log.py` (`_log.info(_NAME, ...)`); arrow geography for the addon bridge is horizontal-right (`←` inbound from addons).
- Daemon quick checks must pass `--confcutdir=tests/daemon` so repo-root browser fixtures do not leak in.
- No frontend build step: plain HTML + vanilla JS, no npm, no bundler, no framework.
- Never use `font-style: italic` anywhere in the UI.
- Hide count badges when the value is 0.
- The WS contract does not change (`GitFileOpenedMsg` already declares `branch`), so **no `API.md` regeneration and no Railway deploy**. `static/` and `daemon/` changes hot-deploy on push to `master`.
- Three repos are touched. Unless stated otherwise, work in `/Users/victorrentea/workspace/training-assistant`. Tasks 7 and 8 work in `/Users/victorrentea/workspace/victor-macos-addons` and `/Users/victorrentea/workspace/live-coding` respectively. Task 9 works in `/Users/victorrentea/workspace/ai`.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `daemon/files_md.py` | Document model, render/parse, resolution, ingestion | 1, 2, 3 |
| `daemon/relink_open_files.py` (new) | One-shot re-resolution pass + CLI | 5 |
| `daemon/addon_bridge_client.py` | Forward `branch` from the WS message | 4 |
| `static/participant.html` | Parse the served markdown, build and render the tree | 6 |
| `tests/daemon/test_files_md.py` | Unit tests for model, format, resolution, ingestion | 1, 2, 3 |
| `tests/daemon/test_relink_open_files.py` (new) | Unit tests for the relink pass | 5 |
| `tests/test_participant_js.js` | Unit tests for `buildFileTree` / `parseFilesMd` | 6 |
| `victor-macos-addons/Sources/VictorAddons/GitRemote.swift` (new) | `httpsRemote` helper, rescued from the deleted monitor | 7 |
| `live-coding/…/openfile/OpenFileReporter.kt` | Circuit breaker | 8 |
| `ai/skills/training-summarizer/SKILL.md` | Relink step + corrected artifact name | 9 |

---

### Task 1: Local-time formatting helpers

The visible time in `opened-files.md` is derived from the canonical UTC `ts`. Two helpers do it: one decides whether the document needs dates, one formats a single timestamp. Pure functions, no I/O — they get their own task because every later render depends on them.

**Files:**
- Modify: `daemon/files_md.py` (add helpers near `_utcnow_iso`, around line 181)
- Test: `tests/daemon/test_files_md.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `files_md._to_local(ts: str) -> datetime` — parses an ISO-8601 UTC string ending in `Z` into an aware local-timezone datetime.
  - `files_md._needs_date(timestamps: list[str]) -> bool` — `True` when the timestamps span more than one local calendar date.
  - `files_md.format_local_time(ts: str, with_date: bool) -> str` — `"09:41"` or `"Aug 4 09:41"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/daemon/test_files_md.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m pytest tests/daemon/test_files_md.py -q --confcutdir=tests/daemon -k "local or needs_date"
```

Expected: FAIL with `AttributeError: module 'daemon.files_md' has no attribute '_to_local'`.

- [ ] **Step 3: Implement the helpers**

In `daemon/files_md.py`, right after `_utcnow_iso`:

```python
def _to_local(ts: str) -> datetime:
    """Parse a canonical UTC timestamp into an aware datetime in the machine's zone."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()


def _needs_date(timestamps: list[str]) -> bool:
    """True when the timestamps do not all fall on the same LOCAL calendar date.

    Decided per document so every entry in a file renders the same way — a
    session that spans midnight or two days must not mix bare times with dated
    ones.
    """
    return len({_to_local(ts).date() for ts in timestamps}) > 1


def format_local_time(ts: str, with_date: bool) -> str:
    """Render a canonical UTC timestamp for humans, in the machine's timezone."""
    dt = _to_local(ts)
    if not with_date:
        return f"{dt:%H:%M}"
    # Built by hand rather than with %-d, which is not portable across libcs.
    return f"{dt:%b} {dt.day} {dt:%H:%M}"
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 -m pytest tests/daemon/test_files_md.py -q --confcutdir=tests/daemon -k "local or needs_date"
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add daemon/files_md.py tests/daemon/test_files_md.py
git commit -m "feat(files): local-time formatting helpers for opened-files.md"
git push origin master
```

---

### Task 2: New document model, render and parse

Replace the basename-keyed model with a path-keyed one that carries a branch per entry and a branch per repo, render the new visible format, and parse both the new and the old format.

**Files:**
- Modify: `daemon/files_md.py:26-140` (regexes, `Entry`, `Repo`, `Doc.render`, `Doc.parse`), `daemon/files_md.py:208-283` (`_load_doc`, delete `_strip_noise_entries` and `_upgrade_unlinked_entries`)
- Test: `tests/daemon/test_files_md.py`

**Interfaces:**
- Consumes: `files_md.format_local_time`, `files_md._needs_date` (Task 1).
- Produces:
  - `files_md.Entry(path: str, branch: str, ts: str, blob_url: str | None = None, ref: str | None = None, reason: str | None = None)` with a read-only `basename` property.
  - `files_md.Repo(url: str, name: str, default_branch: str, branch: str, entries: list[Entry])`.
  - `files_md.Doc.find_repo(url: str) -> Repo | None` — keyed on url alone.
  - `files_md.Doc.render() -> str`, `files_md.Doc.parse(text: str) -> Doc`.

The rendered format, verbatim:

```markdown
# Files opened this session

## [clean-code-java](https://github.com/victorrentea/clean-code-java) — branch `master` <!-- branch:master default_branch:master -->

- [src/main/java/victor/training/cleancode/ComplexIfs.java](https://github.com/victorrentea/clean-code-java/blob/master/src/main/java/victor/training/cleancode/ComplexIfs.java) — 09:41 <!-- ts:2026-08-04T06:41:07Z branch:master ref:branch -->
- [src/main/java/victor/training/cleancode/Immutability.java](https://github.com/victorrentea/clean-code-java/blob/solved/src/main/java/victor/training/cleancode/Immutability.java) — 10:05 · branch `solved` <!-- ts:2026-08-04T07:05:12Z branch:solved ref:branch -->
- src/main/java/victor/training/cleancode/Draft.java — 11:20 <!-- ts:2026-08-04T08:20:31Z branch:master reason:not-pushed -->
```

Note the deviation from the spec's example: `path:` is **gone** from the comment. The visible text already carries the full path (as link text, or as the bare text of an unlinked entry), so duplicating it bought nothing and broke on paths containing spaces. `path:` is still *read* when parsing old documents, where it was authoritative.

- [ ] **Step 1: Write the failing tests**

Replace the existing render/parse tests in `tests/daemon/test_files_md.py` (`test_render_single_repo_linked`, `test_render_single_repo_unlinked`, `test_parse_roundtrip`, `test_count_open_files_counts_entries_across_repos`) with:

```python
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
```

Also delete `test_record_dedup_same_basename_skips` and `test_record_collision_downgrades_to_unlinked` — both assert the basename heuristic this plan removes. Task 3 adds their replacements.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m pytest tests/daemon/test_files_md.py -q --confcutdir=tests/daemon
```

Expected: FAIL with `TypeError: Entry.__init__() got an unexpected keyword argument 'path'` (the old `Entry` takes `basename` first).

- [ ] **Step 3: Rewrite the model, regexes, render and parse**

In `daemon/files_md.py`, replace the module docstring's second bullet, the regex block (lines 26-36) and the dataclasses (lines 39-140) with:

```python
_RE_REPO = re.compile(
    r"^## \[(?P<name>[^\]]+)\]\((?P<url>[^)]+)\).*?<!-- (?P<meta>.*?) -->$"
)
_RE_LINKED = re.compile(
    r"^- \[(?P<text>.+?)\]\((?P<blob>[^)]+)\).*?<!-- (?P<meta>.*?) -->$"
)
_RE_UNLINKED = re.compile(r"^- (?P<text>.+?) +<!-- (?P<meta>.*?) -->$")
_RE_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _parse_meta(text: str) -> dict[str, str]:
    """Split `k:v k:v` metadata. Values never contain spaces; `ts` contains colons,
    so we split on the FIRST colon only."""
    out: dict[str, str] = {}
    for token in text.split():
        key, sep, value = token.partition(":")
        if sep and value:
            out[key] = value
    return out


@dataclass
class Entry:
    path: str
    branch: str
    ts: str
    blob_url: str | None = None
    ref: str | None = None      # "branch" | "default" — which ref resolved the link
    reason: str | None = None   # "not-pushed" | "no-branch" | "rate-limited"

    @property
    def basename(self) -> str:
        return self.path.rsplit("/", 1)[-1]


@dataclass
class Repo:
    url: str
    name: str
    default_branch: str
    branch: str                 # branch of the most recent open in this repo
    entries: list[Entry] = field(default_factory=list)


@dataclass
class Doc:
    repos: list[Repo] = field(default_factory=list)

    def find_repo(self, url: str) -> Repo | None:
        for r in self.repos:
            if r.url == url:
                return r
        return None

    def render(self) -> str:
        if not self.repos:
            return EMPTY_STATE
        with_date = _needs_date([e.ts for r in self.repos for e in r.entries])
        parts = [_TITLE, ""]
        for repo in self.repos:
            parts.append(
                f"## [{repo.name}]({repo.url}) — branch `{repo.branch}` "
                f"<!-- branch:{repo.branch} default_branch:{repo.default_branch} -->"
            )
            parts.append("")
            for e in repo.entries:
                parts.append(_render_entry(e, repo.branch, with_date))
            parts.append("")
        return "\n".join(parts).rstrip() + "\n"

    @classmethod
    def parse(cls, text: str) -> Doc:
        doc = cls()
        if not text or text.strip() == EMPTY_STATE.strip():
            return doc
        current: Repo | None = None
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line:
                continue
            m = _RE_REPO.match(line)
            if m:
                meta = _parse_meta(m.group("meta"))
                default_branch = meta.get("default_branch", "main")
                current = Repo(
                    url=m.group("url"),
                    name=m.group("name"),
                    default_branch=default_branch,
                    # Documents written before branches were tracked have no
                    # `branch:` — everything in them was resolved on the default.
                    branch=meta.get("branch", default_branch),
                )
                doc.repos.append(current)
                continue
            if current is None:
                continue
            entry = _parse_entry(line, current)
            if entry is not None:
                current.entries.append(entry)
        return doc


def _render_entry(e: Entry, repo_branch: str, with_date: bool) -> str:
    time_text = format_local_time(e.ts, with_date)
    # Only spell out the branch when it differs from the repo heading's — and do
    # it in the VISIBLE text, because sanitize_for_wire strips every comment
    # before the document reaches a participant.
    chip = f" · branch `{e.branch}`" if e.branch != repo_branch else ""
    tail = f"ref:{e.ref}" if e.blob_url else f"reason:{e.reason or 'not-pushed'}"
    meta = f"ts:{e.ts} branch:{e.branch} {tail}"
    name = f"[{e.path}]({e.blob_url})" if e.blob_url else e.path
    return f"- {name} — {time_text}{chip} <!-- {meta} -->"


def _parse_entry(line: str, repo: Repo) -> Entry | None:
    """Parse one bullet. Returns None for lines that are not entries, and for
    legacy entries that carry no recoverable path."""
    m = _RE_LINKED.match(line)
    blob_url: str | None = None
    if m:
        blob_url = m.group("blob")
    else:
        m = _RE_UNLINKED.match(line)
        if not m:
            return None
    meta = _parse_meta(m.group("meta"))
    ts = meta.get("ts")
    if not ts:
        return None
    # Three shapes to tell apart, and `branch:` in the metadata is what
    # distinguishes them — never the presence of a "/" in the text, which would
    # silently drop a file sitting at the repo root.
    #   old linked   → `path:` comment is authoritative (text was a basename)
    #   new          → the visible text carries the full path
    #   old unlinked → basename only, nothing to recover: drop it
    text = m.group("text")
    if meta.get("path"):
        path = meta["path"]
    elif "branch" in meta:
        # Unlinked entries put the time after the path; linked ones keep the
        # path inside the [...] and need no trimming.
        path = text.split(" — ", 1)[0] if blob_url is None else text
    else:
        return None
    return Entry(
        path=path,
        branch=meta.get("branch", repo.branch),
        ts=ts,
        blob_url=blob_url,
        ref=meta.get("ref"),
        reason=meta.get("reason"),
    )
```

Import `format_local_time` is unnecessary (same module). Keep `_TITLE`, `EMPTY_STATE`, `atomic_write` and `sanitize_for_wire` as they are.

- [ ] **Step 4: Simplify `_load_doc` and delete the basename machinery**

Replace `daemon/files_md.py:208-283` (`_load_doc`, `_strip_noise_entries`, `_upgrade_unlinked_entries`) with:

```python
def _load_doc(folder: Path) -> Doc:
    target = folder / _FILENAME
    if not target.exists():
        return Doc()
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        _log.error(_NAME, f"read {target} failed: {exc}; starting fresh")
        return Doc()
    try:
        doc = Doc.parse(raw)
    except Exception as exc:  # noqa: BLE001
        _log.error(_NAME, f"parse {target} failed: {exc}; starting fresh")
        return Doc()
    # Rewrite whenever parsing normalised something — that is how a document in
    # the pre-branch format migrates, and how legacy path-less entries get dropped.
    rendered = doc.render()
    if rendered != raw:
        _save_doc(folder, doc)
    return doc
```

Also delete the `_NOISE_BASENAMES` constant and its two usages: the spinner character only ever leaked in through the AppleScript window-title scraper, which Task 7 removes.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python3 -m pytest tests/daemon/test_files_md.py -q --confcutdir=tests/daemon
```

Expected: the render/parse tests pass. Ingestion tests still fail — Task 3 fixes those. If `test_record_*` failures are the only remaining ones, that is the expected state.

- [ ] **Step 6: Commit**

```bash
git add daemon/files_md.py tests/daemon/test_files_md.py
git commit -m "feat(files): path-keyed document model with per-entry branch"
git push origin master
```

---

### Task 3: Branch-aware resolution and ingestion

Resolve a path against the captured branch first, fall back to the default branch, and upsert by `(repo, path)`.

**Files:**
- Modify: `daemon/files_md.py:290-410` (`record_file_opened`, `_record_into_folder`)
- Test: `tests/daemon/test_files_md.py`

**Interfaces:**
- Consumes: `files_md.Entry`, `files_md.Repo`, `files_md.Doc` (Task 2); `github_client.get_repo_info`, `github_client.get_repo_tree`, `github_client.head_blob`, `github_client.build_blob_url`, `github_client.RATE_LIMITED`.
- Produces:
  - `files_md.record_file_opened(url: str, branch: str, file_path: str) -> None` — note the **new middle parameter**; Task 4 calls it with this signature.
  - `files_md.resolve_entry(owner: str, repo: str, branch: str, default_branch: str, path: str) -> tuple[str | None, str | None, str | None]` returning `(blob_url, ref, reason)`. Task 5 reuses it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/daemon/test_files_md.py`, next to the existing `test_record_*` tests (which use the `session_folder` fixture and `_freeze_now` helper already defined in that file):

```python
def _tree(*paths):
    return github_client.RepoTree(
        paths=frozenset(paths),
        paths_by_basename={},
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
```

Update the existing `test_record_*` tests that survive (`test_record_private_repo_writes_nothing`, `test_record_rate_limited_*`, `test_record_empty_path_drops_event`, `test_record_non_github_host_dropped`, `test_repo_url_canonicalisation`) to pass the new middle `branch` argument, e.g. `files_md.record_file_opened(url, "master", "src/a.py")`.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m pytest tests/daemon/test_files_md.py -q --confcutdir=tests/daemon -k record
```

Expected: FAIL with `TypeError: record_file_opened() takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Implement resolution and ingestion**

Replace `daemon/files_md.py:290-410` with:

```python
def _check_ref(owner: str, repo: str, ref: str, path: str) -> tuple[bool, bool]:
    """Probe one git ref. Returns (ref_is_usable, path_is_present_on_it).

    A missing branch and a failed tree call are indistinguishable from the
    GitHub API, so a successful blob HEAD is what proves the ref usable.
    """
    tree = github_client.get_repo_tree(owner, repo, ref)
    if tree is None:
        present = github_client.head_blob(owner, repo, ref, path)
        return present, present
    if tree.truncated:
        return True, github_client.head_blob(owner, repo, ref, path)
    return True, path in tree.paths


def resolve_entry(
    owner: str, repo: str, branch: str, default_branch: str, path: str
) -> tuple[str | None, str | None, str | None]:
    """Resolve one path to a blob URL. Returns (blob_url, ref, reason).

    Captured branch first, default branch second, no link third — see
    docs/superpowers/specs/2026-08-04-open-files-git-linking-design.md.
    """
    branch_usable = True
    if branch:
        branch_usable, present = _check_ref(owner, repo, branch, path)
        if present:
            return github_client.build_blob_url(owner, repo, branch, path), "branch", None
    if branch != default_branch:
        _, present = _check_ref(owner, repo, default_branch, path)
        if present:
            return github_client.build_blob_url(owner, repo, default_branch, path), "default", None
    return None, None, ("not-pushed" if branch_usable else "no-branch")


def record_file_opened(url: str, branch: str, file_path: str) -> None:
    """Process one addon git_file_opened event for the active session."""
    folder = _get_active_session_folder()
    if folder is None:
        return
    migrate_session_if_needed(folder)
    _record_into_folder(folder, url, branch, file_path)


def _record_into_folder(folder: Path, url: str, branch: str, file_path: str) -> None:
    """Record one file event into an explicit session folder.

    Pipeline:
      1. Drop non-github.com hosts and empty paths.
      2. Resolve the repo: cache hit, GitHub API, or rate-limited.
         Private/missing → drop. Rate-limited on an unknown repo → drop (privacy).
      3. Resolve the blob against the captured branch, then the default branch.
      4. Upsert by (repo, path); the repo heading follows the most recent open.
    """
    canonical = _canonical_repo_url(url)
    if canonical is None:
        return

    path = (file_path or "").strip()
    if not path or path == _ADDON_NO_FILE_SENTINEL:
        return

    owner, repo = _owner_repo(canonical)
    info = github_client.get_repo_info(owner, repo)
    if info is None:
        return  # private or 404 — never list

    rate_limited = info is github_client.RATE_LIMITED

    doc = _load_doc(folder)
    repo_obj = doc.find_repo(canonical)

    if rate_limited:
        # Privacy rule: only emit if the repo was already verified public.
        if repo_obj is None:
            return
        default_branch = repo_obj.default_branch
    else:
        default_branch = info.default_branch  # type: ignore[union-attr]

    effective_branch = (branch or "").strip() or default_branch

    if repo_obj is None:
        repo_obj = Repo(url=canonical, name=repo, default_branch=default_branch,
                        branch=effective_branch)
        doc.repos.append(repo_obj)
    else:
        repo_obj.branch = effective_branch
        if not rate_limited:
            repo_obj.default_branch = default_branch

    if rate_limited:
        blob_url, ref, reason = None, None, "rate-limited"
    else:
        blob_url, ref, reason = resolve_entry(owner, repo, effective_branch,
                                              default_branch, path)

    ts = _utcnow_iso()
    existing = next((e for e in repo_obj.entries if e.path == path), None)
    if existing is None:
        repo_obj.entries.append(Entry(path=path, branch=effective_branch, ts=ts,
                                      blob_url=blob_url, ref=ref, reason=reason))
    else:
        existing.branch, existing.ts = effective_branch, ts
        existing.blob_url, existing.ref, existing.reason = blob_url, ref, reason

    _save_doc(folder, doc)
```

Update `migrate_session_if_needed`'s inner loop (`daemon/files_md.py:438-446`) to call `_record_into_folder(folder, url, "", f)` — the `session-state.json` format never carried a branch.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 -m pytest tests/daemon/test_files_md.py -q --confcutdir=tests/daemon
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add daemon/files_md.py tests/daemon/test_files_md.py
git commit -m "feat(files): resolve links on the captured branch with default fallback"
git push origin master
```

---

### Task 4: Pass the branch through the addon bridge

One-line change plus its regression test — the whole feature is dead without it.

**Files:**
- Modify: `daemon/addon_bridge_client.py:29-36`
- Test: `tests/daemon/test_files_md.py`

**Interfaces:**
- Consumes: `files_md.record_file_opened(url, branch, file_path)` (Task 3).
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

```python
def test_bridge_forwards_branch_to_files_md(monkeypatch):
    from daemon import addon_bridge_client
    seen = {}
    monkeypatch.setattr("daemon.files_md.record_file_opened",
                        lambda url, branch, path: seen.update(
                            url=url, branch=branch, path=path))
    addon_bridge_client._handle_git_file_opened({
        "type": "git_file_opened",
        "url": "https://github.com/owner/repo",
        "branch": "solved",
        "file": "src/a.py",
    })
    assert seen == {"url": "https://github.com/owner/repo",
                    "branch": "solved", "path": "src/a.py"}


def test_bridge_tolerates_missing_branch(monkeypatch):
    from daemon import addon_bridge_client
    seen = {}
    monkeypatch.setattr("daemon.files_md.record_file_opened",
                        lambda url, branch, path: seen.update(branch=branch))
    addon_bridge_client._handle_git_file_opened({
        "url": "https://github.com/owner/repo", "file": "src/a.py",
    })
    assert seen == {"branch": ""}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m pytest tests/daemon/test_files_md.py -q --confcutdir=tests/daemon -k bridge
```

Expected: FAIL with `TypeError: <lambda>() missing 1 required positional argument: 'path'`.

- [ ] **Step 3: Forward the branch**

In `daemon/addon_bridge_client.py`, replace `_handle_git_file_opened`:

```python
def _handle_git_file_opened(data: dict) -> None:
    from daemon import files_md
    url = data.get("url", "")
    branch = data.get("branch", "") or ""
    file_path = data.get("file", "")
    if not url or not file_path:
        return
    files_md.record_file_opened(url, branch, file_path)
    log.debug(_NAME, f"← git {url.split('/')[-1]}@{branch or '?'} {file_path}")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 -m pytest tests/daemon/test_files_md.py -q --confcutdir=tests/daemon -k bridge
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add daemon/addon_bridge_client.py tests/daemon/test_files_md.py
git commit -m "fix(files): stop discarding the branch reported by the IDE plugin"
git push origin master
```

---

### Task 5: The relink pass and its CLI

The summarizer runs this before writing anything, so files that were unpushed when opened get their links.

**Files:**
- Create: `daemon/relink_open_files.py`
- Test: `tests/daemon/test_relink_open_files.py`

**Interfaces:**
- Consumes: `files_md.Doc`, `files_md._load_doc`, `files_md._save_doc`, `files_md.resolve_entry`, `files_md._owner_repo`, `files_md.session_filename` (Tasks 2-3); `github_client.get_repo_info`, `github_client.RATE_LIMITED`.
- Produces:
  - `relink_open_files.relink_folder(folder: Path) -> dict[str, int]` returning `{"repos", "entries", "linked_branch", "linked_default", "unlinked"}`.
  - CLI: `python3 -m daemon.relink_open_files [--session-folder PATH]`, printing that dict as JSON.

- [ ] **Step 1: Write the failing tests**

Create `tests/daemon/test_relink_open_files.py`:

```python
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
    return github_client.RepoTree(paths=frozenset(paths), paths_by_basename={},
                                  truncated=False)


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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python3 -m pytest tests/daemon/test_relink_open_files.py -q --confcutdir=tests/daemon
```

Expected: FAIL with `ImportError: cannot import name 'relink_open_files' from 'daemon'`.

- [ ] **Step 3: Implement the module**

Create `daemon/relink_open_files.py`:

```python
"""Re-resolve every link in a session's opened-files.md.

Files opened during live coding are frequently not committed yet, so their
links cannot be built at open time. This pass runs later — the training
summarizer invokes it before writing anything — when the code has usually been
pushed. It re-resolves EVERY entry, not just the unlinked ones, so a link built
on a branch that has since been deleted degrades instead of rotting.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from daemon import files_md, github_client
from daemon import log as _log

_NAME = "relink"


def relink_folder(folder: Path) -> dict[str, int]:
    """Re-resolve one session folder. Returns a counts summary."""
    summary = {"repos": 0, "entries": 0, "linked_branch": 0,
               "linked_default": 0, "unlinked": 0}
    if not (folder / files_md.session_filename()).exists():
        return summary

    doc = files_md._load_doc(folder)
    for repo_obj in doc.repos:
        owner, repo = files_md._owner_repo(repo_obj.url)
        info = github_client.get_repo_info(owner, repo)
        if info is None or info is github_client.RATE_LIMITED:
            # Leave the block untouched: a 404 or a rate limit here says more
            # about the network than about the repo.
            _log.info(_NAME, f"skipping {repo_obj.url} (unavailable)")
            continue
        summary["repos"] += 1
        repo_obj.default_branch = info.default_branch
        for entry in repo_obj.entries:
            blob_url, ref, reason = files_md.resolve_entry(
                owner, repo, entry.branch, info.default_branch, entry.path)
            entry.blob_url, entry.ref, entry.reason = blob_url, ref, reason
            summary["entries"] += 1
            if ref == "branch":
                summary["linked_branch"] += 1
            elif ref == "default":
                summary["linked_default"] += 1
            else:
                summary["unlinked"] += 1

    files_md._save_doc(folder, doc)
    _log.info(_NAME, f"relinked {folder.name}: {summary}")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-resolve GitHub links in a session's opened-files.md")
    parser.add_argument("--session-folder", type=Path, default=None,
                        help="session folder; defaults to the active session")
    args = parser.parse_args(argv)

    folder = args.session_folder
    if folder is None:
        from daemon.misc.content_files import get_active_session_folder
        folder = get_active_session_folder()
    if folder is None:
        print(json.dumps({"error": "no active session"}), file=sys.stderr)
        return 1

    print(json.dumps(relink_folder(Path(folder))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python3 -m pytest tests/daemon/test_relink_open_files.py -q --confcutdir=tests/daemon
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add daemon/relink_open_files.py tests/daemon/test_relink_open_files.py
git commit -m "feat(files): relink pass for files not yet pushed when opened"
git push origin master
```

---

### Task 6: Participant Files tab — folder tree

Replace the flat `marked.parse` rendering with a parsed tree. The tree builder is a top-level function so `tests/test_participant_js.js` can extract and exercise the shipped code.

**Files:**
- Modify: `static/participant.html:20-21` (CSS), `static/participant.html:4542-4548` (unread rule), `static/participant.html:5080-5121` (`loadFilesMd`)
- Test: `tests/test_participant_js.js`

**Interfaces:**
- Consumes: the markdown format from Task 2, after `sanitize_for_wire` has stripped all HTML comments.
- Produces (all top-level functions in `static/participant.html`):
  - `parseFilesMd(md)` → `[{name, url, branch, entries: [{path, href, time, branch}]}]`
  - `buildFileTree(paths)` → `{name, folders: [...], files: [{name, path}]}` (root, never collapsed)
  - `finalizeFileNode(node, allowCollapse)` → the same node shape, collapsed and sorted

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_participant_js.js`, before the final pass/fail summary:

```js
const buildFileTree = new Function(
  extractFunction(PARTICIPANT_HTML, 'finalizeFileNode') + ';' +
  extractFunction(PARTICIPANT_HTML, 'buildFileTree') + '; return buildFileTree;'
)();
const parseFilesMd = new Function(
  extractFunction(PARTICIPANT_HTML, 'parseFilesMd') + '; return parseFilesMd;'
)();

console.log('buildFileTree()');

const SAMPLE = [
  'README.md',
  'src/main/java/victor/training/cleancode/ComplexIfs.java',
  'src/main/java/victor/training/cleancode/Immutability.java',
  'src/main/java/victor/training/cleancode/fp/Optionals.java',
  'src/main/java/victor/training/cleancode/fp/Streams.java',
  'src/test/java/victor/training/cleancode/ComplexIfsTest.java',
];
const tree = buildFileTree(SAMPLE);

assert('root keeps its own file', tree.files.map(f => f.name).join() === 'README.md');
assert('root is not collapsed into src', tree.folders.length === 1 && tree.folders[0].name === 'src');

const src = tree.folders[0];
assert('src stays a node because it branches',
  src.folders.map(f => f.name).join() === 'main/java/victor/training/cleancode,test/java/victor/training/cleancode');

const main = src.folders[0];
assert('single-child chain is collapsed into one node',
  main.name === 'main/java/victor/training/cleancode');
assert('folders come before files', main.folders.length === 1 && main.folders[0].name === 'fp');
assert('files of the collapsed node are kept',
  main.files.map(f => f.name).join() === 'ComplexIfs.java,Immutability.java');
assert('leaf folder holds its files sorted',
  main.folders[0].files.map(f => f.name).join() === 'Optionals.java,Streams.java');
assert('file entries keep their full path',
  main.files[0].path === 'src/main/java/victor/training/cleancode/ComplexIfs.java');

// A folder with a file of its own must NOT be collapsed into its single child,
// or that file would be orphaned.
const guard = buildFileTree(['a/b/c.java', 'a/d.java']);
assert('no collapse when the folder has files of its own',
  guard.folders[0].name === 'a' && guard.folders[0].files.map(f => f.name).join() === 'd.java');
assert('the single child still renders below it',
  guard.folders[0].folders[0].name === 'b');

const mixed = buildFileTree(['Zebra.java', 'alpha.java']);
assert('sorting is case-insensitive',
  mixed.files.map(f => f.name).join() === 'alpha.java,Zebra.java');

assert('empty input yields an empty root',
  buildFileTree([]).folders.length === 0 && buildFileTree([]).files.length === 0);

console.log('parseFilesMd()');

const MD = [
  '# Files opened this session',
  '',
  '## [clean-code-java](https://github.com/victorrentea/clean-code-java) — branch `master` ',
  '',
  '- [src/a/B.java](https://github.com/victorrentea/clean-code-java/blob/master/src/a/B.java) — 09:41 ',
  '- [src/a/C.java](https://github.com/victorrentea/clean-code-java/blob/solved/src/a/C.java) — 10:05 · branch `solved` ',
  '- src/a/Draft.java — 11:20 ',
].join('\n');
const repos = parseFilesMd(MD);

assert('one repo parsed', repos.length === 1);
assert('repo name and branch parsed',
  repos[0].name === 'clean-code-java' && repos[0].branch === 'master');
assert('three entries parsed', repos[0].entries.length === 3);
assert('linked entry keeps path and href',
  repos[0].entries[0].path === 'src/a/B.java' &&
  repos[0].entries[0].href.endsWith('/blob/master/src/a/B.java'));
assert('time parsed', repos[0].entries[0].time === '09:41');
assert('divergent branch chip parsed', repos[0].entries[1].branch === 'solved');
assert('same-branch entry has no chip', repos[0].entries[0].branch === '');
assert('unlinked entry has no href and keeps its path',
  repos[0].entries[2].href === null && repos[0].entries[2].path === 'src/a/Draft.java');

const dated = parseFilesMd([
  '## [r](https://github.com/o/r) — branch `main` ',
  '- [a.java](https://github.com/o/r/blob/main/a.java) — Aug 4 09:41 ',
].join('\n'));
assert('dated times parse', dated[0].entries[0].time === 'Aug 4 09:41');
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
node tests/test_participant_js.js
```

Expected: throws `Error: function not found: finalizeFileNode in .../static/participant.html`.

- [ ] **Step 3: Implement parsing, tree building and rendering**

In `static/participant.html`, replace `loadFilesMd` and the now-unused `_filesRawMarkdown` variable (lines 5080-5121) with:

```js
var _filesDirty = true;

// Parse the sanitized opened-files.md. Every HTML comment is stripped server-side,
// so everything below must come out of the VISIBLE text.
function parseFilesMd(md) {
  var repos = [];
  var current = null;
  (md || '').split('\n').forEach(function (raw) {
    var line = raw.trim();
    if (!line) return;
    var m = line.match(/^## \[([^\]]+)\]\(([^)]+)\)(?: — branch `([^`]+)`)?/);
    if (m) {
      current = { name: m[1], url: m[2], branch: m[3] || '', entries: [] };
      repos.push(current);
      return;
    }
    if (!current) return;
    m = line.match(/^- \[(.+?)\]\((\S+)\)(?: — ([0-9A-Za-z: ]+?))?(?: · branch `([^`]+)`)?$/);
    if (m) {
      current.entries.push({ path: m[1], href: m[2], time: m[3] || '', branch: m[4] || '' });
      return;
    }
    m = line.match(/^- (?!\[)(.+?)(?: — ([0-9A-Za-z: ]+?))?(?: · branch `([^`]+)`)?$/);
    if (m) {
      current.entries.push({ path: m[1], href: null, time: m[2] || '', branch: m[3] || '' });
    }
  });
  return repos;
}

// Collapse single-child folder chains and sort. `allowCollapse` is false for the
// root only — the repo root itself is never merged into its first folder.
function finalizeFileNode(node, allowCollapse) {
  var names = Object.keys(node.folders);
  while (allowCollapse && node.files.length === 0 && names.length === 1) {
    var only = node.folders[names[0]];
    node = {
      name: node.name ? node.name + '/' + only.name : only.name,
      folders: only.folders,
      files: only.files
    };
    names = Object.keys(node.folders);
  }
  function byName(a, b) {
    return a.name.toLowerCase().localeCompare(b.name.toLowerCase());
  }
  var folders = names.map(function (n) { return finalizeFileNode(node.folders[n], true); });
  folders.sort(byName);
  return { name: node.name, folders: folders, files: node.files.slice().sort(byName) };
}

function buildFileTree(paths) {
  var root = { name: '', folders: {}, files: [] };
  (paths || []).forEach(function (p) {
    var parts = p.split('/');
    var node = root;
    for (var i = 0; i < parts.length - 1; i++) {
      var seg = parts[i];
      if (!node.folders[seg]) node.folders[seg] = { name: seg, folders: {}, files: [] };
      node = node.folders[seg];
    }
    node.files.push({ name: parts[parts.length - 1], path: p });
  });
  return finalizeFileNode(root, false);
}

function _renderFileNode(node, byPath, depth, out) {
  node.folders.forEach(function (folder) {
    var row = document.createElement('div');
    row.className = 'file-tree-folder';
    row.style.paddingLeft = (depth * 1.1) + 'rem';
    row.textContent = '▾ ' + folder.name;
    out.appendChild(row);
    _renderFileNode(folder, byPath, depth + 1, out);
  });
  node.files.forEach(function (file) {
    var entry = byPath[file.path] || {};
    var row = document.createElement('div');
    row.className = 'file-tree-file';
    row.style.paddingLeft = (depth * 1.1) + 'rem';
    if (entry.href) {
      var a = document.createElement('a');
      a.href = entry.href;
      a.target = '_blank';
      a.rel = 'noopener';
      a.textContent = file.name;
      row.appendChild(a);
    } else {
      row.appendChild(document.createTextNode(file.name));
    }
    if (entry.time) {
      var t = document.createElement('span');
      t.className = 'file-tree-time';
      t.textContent = entry.time;
      row.appendChild(t);
    }
    if (entry.branch) {
      var chip = document.createElement('span');
      chip.className = 'file-tree-branch';
      chip.textContent = entry.branch;
      row.appendChild(chip);
    }
    out.appendChild(row);
  });
}

async function loadFilesMd() {
  if (!_filesDirty) return;
  _filesDirty = false;
  const el = document.getElementById('files-content');
  el.textContent = 'Loading…';
  try {
    const data = await fetch(`/${_sessionId}/api/participant/files-md`).then(r => r.ok ? r.json() : Promise.reject('not found'));
    const repos = parseFilesMd((data && data.raw_markdown) || '');
    if (!repos.length) { el.textContent = 'No files opened yet.'; return; }
    el.textContent = '';
    repos.forEach(function (repo) {
      var head = document.createElement('div');
      head.className = 'file-tree-repo';
      var link = document.createElement('a');
      link.href = repo.url;
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = repo.name;
      head.appendChild(link);
      if (repo.branch) {
        var chip = document.createElement('span');
        chip.className = 'file-tree-branch';
        chip.textContent = repo.branch;
        head.appendChild(chip);
      }
      el.appendChild(head);
      var byPath = {};
      repo.entries.forEach(function (e) { byPath[e.path] = e; });
      _renderFileNode(buildFileTree(repo.entries.map(function (e) { return e.path; })),
                      byPath, 0, el);
    });
  } catch (e) {
    el.textContent = 'Failed to load files.';
    _filesDirty = true;
  }
}
```

- [ ] **Step 4: Add the styles**

Replace `static/participant.html:21` (the `.file-path-dir` rule, now unused) with:

```css
#files-content .file-tree-repo{font-weight:700;margin:.75rem 0 .35rem}
#files-content .file-tree-folder{opacity:.8;white-space:nowrap;overflow-x:auto;line-height:1.8}
#files-content .file-tree-file{white-space:nowrap;overflow-x:auto;line-height:1.8}
#files-content .file-tree-time{color:var(--color-on-surface-variant,#888);font-size:.78em;margin-left:.5rem}
#files-content .file-tree-branch{font-size:.72em;padding:1px 6px;border-radius:999px;border:1px solid currentColor;opacity:.7;margin-left:.4rem}
```

- [ ] **Step 5: Stop re-flagging the tab unread when only a timestamp moved**

Timestamps now change on every re-open, which rewrites `opened-files.md` and fires `files_count_updated` with an unchanged count. Without this, re-opening a file participants already saw makes the badge shout "new" again. In `static/participant.html:4542-4548`:

```js
    case 'files_count_updated': {
      var previousFilesCount = _lastFilesCount;
      _lastFilesCount = msg.count;
      _setFilesBadge(msg.count);
      var onFiles = document.getElementById('files-view').style.display !== 'none';
      if (onFiles) { loadFilesMd(); _applyFilesBadgeUnread(false); }
      else {
        _filesDirty = true;
        // Only a genuinely new file earns the unread flag; a re-opened file
        // rewrites the document without changing the count.
        if (msg.count > previousFilesCount) _applyFilesBadgeUnread(true);
      }
      break;
    }
```

Declare `var _lastFilesCount = 0;` next to `var _filesDirty = true;`, and set it in the state handler at `static/participant.html:3916` (`_lastFilesCount = state.files_count || 0;`).

- [ ] **Step 6: Run the tests to verify they pass**

```bash
node tests/test_participant_js.js
```

Expected: all assertions pass, exit code 0.

- [ ] **Step 7: Visual proof**

Start the daemon (`python3 -m daemon`), open `http://localhost:8081/`, seed a session's `opened-files.md` with the multi-package sample from the tests, open the participant page's Files tab, and screenshot it. Confirm: `src` is a node, `main/java/victor/training/cleancode` is one collapsed row, `fp` sorts before the files, times are grey and adjacent to the names.

- [ ] **Step 8: Commit**

```bash
git add static/participant.html tests/test_participant_js.js
git commit -m "feat(participant): render opened files as a folder tree"
git push origin master
```

---

### Task 7: macOS addon cleanup

Delete the AppleScript window-title scraper — dormant since the plugin took over — while rescuing the one helper the live path still calls.

**Files:** (all in `/Users/victorrentea/workspace/victor-macos-addons`)
- Create: `Sources/VictorAddons/GitRemote.swift`
- Delete: `Sources/VictorAddons/IntelliJMonitor.swift`
- Modify: `Sources/VictorAddons/AppDelegate.swift:1110-1139`, `Sources/VictorAddons/LocalWebSocketServer.swift:122-130`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `GitRemote.https(_ remoteURL: String) -> String` — replaces `IntelliJMonitor.httpsRemote(_:)`.

- [ ] **Step 1: Create the rescued helper**

`Sources/VictorAddons/GitRemote.swift`:

```swift
import Foundation

/// Normalizes git remote URLs to their canonical https form.
/// Extracted from the deleted IntelliJMonitor, which the plugin superseded —
/// the plugin-POST handler still needs it.
enum GitRemote {
    /// e.g. `git@github.com:owner/repo.git` → `https://github.com/owner/repo`
    static func https(_ remoteURL: String) -> String {
        var url = remoteURL
        if url.hasPrefix("git@") {
            url = url.replacingOccurrences(of: ":", with: "/")
                .replacingOccurrences(of: "git@", with: "https://")
        }
        return url.replacingOccurrences(of: "\\.git$", with: "", options: .regularExpression)
    }
}
```

- [ ] **Step 2: Delete the monitor and rewire its one caller**

```bash
rm Sources/VictorAddons/IntelliJMonitor.swift
```

In `AppDelegate.swift`, delete the whole block that constructs `ijMonitor` (the `let ijMonitor = IntelliJMonitor(...)` statement, its `onGitFileOpened` closure, the commented-out `ijMonitor.start()` and `self.ijMonitor = ijMonitor`), plus the `ijMonitor` stored property. In the surviving `onIntellijFileOpened` handler, replace `IntelliJMonitor.httpsRemote(rawUrl)` with `GitRemote.https(rawUrl)`, and drop the `fileURL:` argument:

```swift
            let url = GitRemote.https(rawUrl)
            let branch = (json["branch"] as? String) ?? ""
            self?.wsServer?.pushGitFileOpened(url: url, branch: branch, file: file)
```

- [ ] **Step 3: Drop the unused `fileURL` from the WS push**

In `LocalWebSocketServer.swift`:

```swift
    func pushGitFileOpened(url: String, branch: String, file: String) {
        let msg: [String: Any] = ["type": "git_file_opened", "url": url,
                                  "branch": branch, "file": file]
        guard let data = try? JSONSerialization.data(withJSONObject: msg),
              let text = String(data: data, encoding: .utf8) else { return }
        queue.async { [weak self] in
            self?.broadcast(text)
        }
    }
```

`GitFileOpenedMsg.file_url` stays declared and optional on the daemon side, so an older addon binary still validates.

- [ ] **Step 4: Build to verify**

```bash
cd /Users/victorrentea/workspace/victor-macos-addons && swift build 2>&1 | tail -20
```

Expected: build succeeds with no reference to `IntelliJMonitor`. Confirm with `grep -rn "IntelliJMonitor" Sources/` returning nothing.

- [ ] **Step 5: Commit**

```bash
cd /Users/victorrentea/workspace/victor-macos-addons
git add -A Sources/VictorAddons
git commit -m "refactor(addons): delete the AppleScript IntelliJ monitor superseded by the plugin"
git push origin master
```

---

### Task 8: IntelliJ plugin circuit breaker

Keep the plugin silent on machines with no addon, without adding a probe, a thread, or a loop.

**Files:** (in `/Users/victorrentea/workspace/live-coding`)
- Modify: `src/main/kotlin/com/github/victorrentea/livecoding/openfile/OpenFileReporter.kt:102-124`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add the breaker state and gate**

In `OpenFileReporter`, add fields next to `lastSentKey`:

```kotlin
    private var consecutiveFailures = 0
    private var lastAttemptMillis = 0L
```

and add a companion constant next to `DWELL_SECONDS`:

```kotlin
        private const val FAILURES_BEFORE_BACKOFF = 3
        private const val BACKOFF_MILLIS = 5 * 60 * 1000L
```

- [ ] **Step 2: Gate and update the breaker inside `post`**

Replace `post` with:

```kotlin
    private fun post(payload: Payload) {
        // No separate liveness probe: a connect to 127.0.0.1 with nothing
        // listening is refused instantly (ECONNREFUSED, not a timeout), so the
        // POST we were going to send anyway IS the check. After a few refusals
        // we go quiet, retrying at most once every BACKOFF_MILLIS — enough to
        // recover if the add-on starts after the IDE, quiet enough to be
        // invisible on a machine that has no add-on at all.
        val now = System.currentTimeMillis()
        synchronized(lock) {
            if (consecutiveFailures >= FAILURES_BEFORE_BACKOFF &&
                now - lastAttemptMillis < BACKOFF_MILLIS) return
            lastAttemptMillis = now
        }

        val url = AppSettingsState.getInstance().addonReportUrl
        val json = buildString {
            append('{')
            append("\"url\":").append(jsonString(payload.url)).append(',')
            append("\"branch\":").append(jsonString(payload.branch)).append(',')
            append("\"file\":").append(jsonString(payload.file)).append(',')
            append("\"project\":").append(jsonString(payload.project))
            append('}')
        }
        try {
            HttpRequests.post(url, "application/json")
                .connectTimeout(1500)
                .readTimeout(1500)
                .connect { request ->
                    request.write(json)
                    request.readString() // complete the round-trip; ignore the body
                }
            synchronized(lock) { consecutiveFailures = 0 }
            log.debug("reported open file to add-on: ${payload.file}")
        } catch (e: Exception) {
            val failures = synchronized(lock) { ++consecutiveFailures }
            if (failures == FAILURES_BEFORE_BACKOFF) {
                log.info("add-on unreachable at $url; backing off to one attempt every 5 minutes")
            }
            log.debug("failed to report open file to add-on at $url: ${e.message}")
        }
    }
```

- [ ] **Step 3: Reset the breaker when the setting is toggled back on**

`report()` already returns early when `reportOpenFileToAddon` is false. Add, in `candidateChanged`, right after that same early-return guard:

```kotlin
    fun candidateChanged(project: Project, file: VirtualFile?) {
        if (!AppSettingsState.getInstance().reportOpenFileToAddon) {
            synchronized(lock) { consecutiveFailures = 0 }  // a manual re-enable deserves a fresh try
            return
        }
```

- [ ] **Step 4: Compile to verify**

```bash
cd /Users/victorrentea/workspace/live-coding && ./gradlew compileKotlin 2>&1 | tail -20
```

Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 5: Commit**

```bash
cd /Users/victorrentea/workspace/live-coding
git add src/main/kotlin/com/github/victorrentea/livecoding/openfile/OpenFileReporter.kt
git commit -m "feat(openfile): back off when no add-on is listening"
git push origin master
```

---

### Task 9: Summarizer skill — relink step and corrected artifact name

**Files:** (in `/Users/victorrentea/workspace/ai`)
- Modify: `skills/training-summarizer/SKILL.md`

**Interfaces:**
- Consumes: the CLI from Task 5 (`python3 -m daemon.relink_open_files --session-folder <folder>`).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Correct the stale artifact name**

At `SKILL.md:14`, replace `<folder>/files.md` with `<folder>/opened-files.md`. Search the whole file for any other `files.md` reference and fix those too:

```bash
cd /Users/victorrentea/workspace/ai && grep -n "files\.md" skills/training-summarizer/SKILL.md
```

- [ ] **Step 2: Add the relink step**

Insert a new step immediately before the current Step 1 (folder discovery is a prerequisite, so this goes right after the folder is known — renumber the following steps):

```markdown
## Step 2 — Relink the opened files (do this before reading anything)

Files opened during live coding are often not committed yet at the moment they
are opened, so the daemon could not build their GitHub links. Repair them now,
while the code has since been pushed:

    cd ~/workspace/training-assistant && python3 -m daemon.relink_open_files --session-folder "<folder>"

It prints a JSON summary — `{"repos":…,"entries":…,"linked_branch":…,"linked_default":…,"unlinked":…}`.
Report those counts. A non-zero `unlinked` is normal (a branch that was never
pushed), not an error.

This has to run before the summary is written, so that `<folder>/opened-files.md`
holds the correct links: the link-verification subagents consult it to attach a
section to the file it discusses, citing the exact path on the branch it was
shown from.
```

- [ ] **Step 3: Verify the CLI reference is real**

```bash
cd ~/workspace/training-assistant && python3 -m daemon.relink_open_files --help
```

Expected: argparse usage showing `--session-folder`.

- [ ] **Step 4: Commit and refresh the Copilot cache**

```bash
cd /Users/victorrentea/workspace/ai
git add skills/training-summarizer/SKILL.md
git commit -m "feat(summarizer): relink opened files before summarizing"
git push origin master
# Copilot CLI reads this marketplace from the REMOTE repo, so it only sees
# what has been pushed — refresh its cache.
copilot plugin update victor-skills
```

---

## Final verification

- [ ] Run the full hook-parity check:

```bash
cd /Users/victorrentea/workspace/training-assistant
uv run --extra dev --extra daemon --extra telemetry bash tests/check-all.sh
```

(On Apple Silicon, prefix with `arch -arm64`.)

- [ ] Run the JS tests, which `check-all.sh` does **not** cover:

```bash
node tests/test_participant_js.js
```

- [ ] Update `ARCHITECTURE.md` if the C4 diagrams name `IntelliJMonitor`:

```bash
grep -rn "IntelliJMonitor" ARCHITECTURE.md docs/
```

- [ ] Record the change in `backlog.md`.

- [ ] Confirm the daemon picked the change up in production: after the push, `curl -s https://interact.victorrentea.ro/api/status` and check `daemon_code_timestamp` moved. No Railway redeploy is expected — `railway/**` is untouched, so "No deployment needed - watched paths not modified" is the correct outcome, not a failure.
