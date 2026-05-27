# files.md Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the collapsible git-repos navbar entry on the participant page with a single non-collapsible "Files" entry backed by a per-session `files.md` (rendered like AI summary). All feature state moves out of `session-state.json` and into the markdown file itself; only public GitHub repos are listed; blob links are verified before being written; same-basename collisions downgrade entries to unlinked.

**Architecture:** A new `daemon/files_md.py` module owns parsing, dedup, and atomic writes of `<session>/files.md`. A new `daemon/github_client.py` provides `get_repo_info()` and `head_blob()` with in-process caching. The addon WS handler at `daemon/addon_bridge_client.py:172` swaps `participant_state.accumulate_git_file(...)` for `files_md.record_file_opened(...)`. A new `GET /api/participant/files-md` endpoint returns JSON `{raw_markdown, updated_at}` after stripping HTML comments — matching the existing `/summary` endpoint pattern. The participant UI replaces the `gitrepos` nav entry with a `Files` entry that calls `showView('files')` / `loadFilesMd()` (mirroring `loadSummary()`).

**Tech Stack:** Python 3.13 / FastAPI / Pydantic, Pytest, `urllib.request` (consistent with existing daemon HTTP — see `daemon/participant/router.py:_http_get_json`), vanilla JS / marked.js on the frontend.

**Railway note:** Railway already proxies `/api/participant/{path:path}` to the daemon via wildcard (`railway/features/ws/proxy_bridge.py:95`). No Railway-side route additions or removals needed.

**Spec:** `docs/superpowers/specs/2026-05-27-files-md-redesign-design.md`

---

## File Structure

**New files:**

| Path | Responsibility |
| --- | --- |
| `daemon/files_md.py` | Parse, mutate, atomically write `files.md`. Public entry: `record_file_opened(url, file_path)`. Migration helper. Wire sanitization. |
| `daemon/github_client.py` | Tiny HTTP wrapper: `get_repo_info(owner, repo)`, `head_blob(owner, repo, branch, path)`, in-process cache. |
| `tests/daemon/test_files_md.py` | Unit tests for `files_md` (parse, dedup, collision, sanitize, migrate). |
| `tests/daemon/test_github_client.py` | Unit tests for `github_client` (stubbed urllib). |
| `tests/docker/test_files_md_e2e.py` | Hermetic E2E (nightly). |

**Modified files:**

| Path | Change |
| --- | --- |
| `daemon/addon_bridge_client.py:166-180` | Call `files_md.record_file_opened` instead of `participant_state.accumulate_git_file`. |
| `daemon/misc/router.py` | Add `GET /api/participant/files-md` returning JSON `{raw_markdown, updated_at}`. |
| `daemon/participant/state.py` | Remove `GitRepoActivity`, `git_repos` field, `accumulate_git_file()`, snapshot/reset/restore handling of `git_repos`. |
| `daemon/participant/router.py` | Remove `GitActivityResponse`, `/git-activity` endpoint, `git_files_count` field, `last_git_url` field. |
| `daemon/openapi_contract_metadata.py:28-31` | Remove `/api/participant/git-activity` branch. |
| `static/participant.html` | Replace `gitrepos` nav block with `files` nav entry; remove `toggleRepos`/`openRepos`/`closeRepos`/`#repos-content`/`#code-badge`; add `#files-content` pane and `loadFilesMd()` mirroring `loadSummary()`. |
| `docs/openapi.yaml` | Regenerated. |
| `API.md` | Regenerated via `python3 scripts/generate_apis_md.py --output API.md`. |

---

## On-disk `files.md` format reference

```markdown
# Files opened this session

## [training-assistant](https://github.com/victorrentea/training-assistant) <!-- default_branch:master -->

- [participant.html](https://github.com/victorrentea/training-assistant/blob/master/static/participant.html) <!-- ts:2026-05-27T14:23:45Z path:static/participant.html -->
- utils.py <!-- ts:2026-05-27T14:25:01Z reason:ambiguous -->
```

Empty state:

```markdown
# Files opened this session

No files opened yet
```

**Repo URL canonicalisation:** strip trailing `.git` and any trailing slash before storing. Display name is the last path component.

**HTML comments stripped on the wire** by `files_md.sanitize_for_wire(text)` via regex `<!--.*?-->`.

---

## Task 1: `files_md.py` — parse + write skeleton

Establish the data model and atomic-write plumbing with no GitHub or dedup logic yet. Pure data round-trip.

**Files:**
- Create: `daemon/files_md.py`
- Create: `tests/daemon/test_files_md.py`

- [ ] **Step 1: Write the failing test for empty-state file content**

```python
# tests/daemon/test_files_md.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
bash tests/run-daemon-tests.sh -k test_files_md -v 2>&1 | tee logs/plan-step.log
```

Expected: ImportError / module not found for `daemon.files_md`.

- [ ] **Step 3: Implement `daemon/files_md.py` skeleton**

```python
"""files.md — the canonical store of files opened during a session.

All feature state lives in the markdown file itself:
- Repo default branch cached in `<!-- default_branch:... -->` on the `##` heading.
- File first-open timestamp + path/reason cached in HTML comments on each bullet.

HTML comments are stripped before serving to participants — see `sanitize_for_wire`.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

EMPTY_STATE = "# Files opened this session\n\nNo files opened yet\n"

_TITLE = "# Files opened this session"

_RE_REPO = re.compile(
    r"^## \[(?P<name>[^\]]+)\]\((?P<url>[^)]+)\) <!-- default_branch:(?P<branch>[^ ]+) -->$"
)
_RE_LINKED = re.compile(
    r"^- \[(?P<basename>[^\]]+)\]\((?P<blob>[^)]+)\) "
    r"<!-- ts:(?P<ts>[^ ]+) path:(?P<path>[^ ]+) -->$"
)
_RE_UNLINKED = re.compile(
    r"^- (?P<basename>\S+) <!-- ts:(?P<ts>[^ ]+) reason:(?P<reason>[^ ]+) -->$"
)
_RE_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass
class Entry:
    basename: str
    blob_url: str | None
    path: str | None
    ts: str
    reason: str | None


@dataclass
class Repo:
    url: str
    name: str
    default_branch: str
    entries: list[Entry] = field(default_factory=list)


@dataclass
class Doc:
    repos: list[Repo] = field(default_factory=list)

    def find_repo(self, url: str) -> Repo | None:
        for r in self.repos:
            if r.url == url:
                return r
        return None

    def find_entry(self, repo_url: str, basename: str) -> Entry | None:
        repo = self.find_repo(repo_url)
        if repo is None:
            return None
        for e in repo.entries:
            if e.basename == basename:
                return e
        return None

    def render(self) -> str:
        if not self.repos:
            return EMPTY_STATE
        parts = [_TITLE, ""]
        for repo in self.repos:
            parts.append(
                f"## [{repo.name}]({repo.url}) <!-- default_branch:{repo.default_branch} -->"
            )
            parts.append("")
            for e in repo.entries:
                if e.blob_url and e.path:
                    parts.append(
                        f"- [{e.basename}]({e.blob_url}) <!-- ts:{e.ts} path:{e.path} -->"
                    )
                else:
                    parts.append(
                        f"- {e.basename} <!-- ts:{e.ts} reason:{e.reason or 'no-path'} -->"
                    )
            parts.append("")
        text = "\n".join(parts).rstrip() + "\n"
        return text

    @classmethod
    def parse(cls, text: str) -> "Doc":
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
                current = Repo(
                    url=m.group("url"),
                    name=m.group("name"),
                    default_branch=m.group("branch"),
                )
                doc.repos.append(current)
                continue
            if current is None:
                continue
            m = _RE_LINKED.match(line)
            if m:
                current.entries.append(
                    Entry(
                        basename=m.group("basename"),
                        blob_url=m.group("blob"),
                        path=m.group("path"),
                        ts=m.group("ts"),
                        reason=None,
                    )
                )
                continue
            m = _RE_UNLINKED.match(line)
            if m:
                current.entries.append(
                    Entry(
                        basename=m.group("basename"),
                        blob_url=None,
                        path=None,
                        ts=m.group("ts"),
                        reason=m.group("reason"),
                    )
                )
        return doc


def atomic_write(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


def sanitize_for_wire(text: str) -> str:
    return _RE_COMMENT.sub("", text)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
bash tests/run-daemon-tests.sh -k test_files_md -v 2>&1 | tee logs/plan-step.log
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add daemon/files_md.py tests/daemon/test_files_md.py
git commit -m "feat(daemon): files_md skeleton — parse, render, atomic write"
```

---

## Task 2: `github_client.py` — repo info + blob HEAD

Encapsulate GitHub HTTP calls with an in-process cache. No business logic.

**Files:**
- Create: `daemon/github_client.py`
- Create: `tests/daemon/test_github_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/daemon/test_github_client.py
from unittest.mock import patch

import pytest

from daemon import github_client


@pytest.fixture(autouse=True)
def reset_cache():
    github_client.reset_cache()
    yield
    github_client.reset_cache()


def _fake_resp(status: int, body: bytes = b"{}", headers: dict | None = None):
    class _Resp:
        def __init__(self):
            self.status = status
            self._body = body
            self.headers = headers or {}

        def read(self):
            return self._body

        def getcode(self):
            return self.status

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp()


def test_get_repo_info_public_returns_default_branch():
    body = b'{"default_branch":"main"}'
    with patch("urllib.request.urlopen", return_value=_fake_resp(200, body)):
        info = github_client.get_repo_info("owner", "repo")
    assert info is not None
    assert info.default_branch == "main"


def test_get_repo_info_404_returns_none():
    import urllib.error
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError("u", 404, "Not Found", {}, None),
    ):
        info = github_client.get_repo_info("owner", "missing")
    assert info is None


def test_get_repo_info_403_returns_none():
    import urllib.error
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError("u", 403, "Forbidden", {}, None),
    ):
        info = github_client.get_repo_info("owner", "private")
    assert info is None


def test_get_repo_info_is_cached_after_success():
    body = b'{"default_branch":"main"}'
    with patch("urllib.request.urlopen", return_value=_fake_resp(200, body)) as mock:
        github_client.get_repo_info("owner", "repo")
        github_client.get_repo_info("owner", "repo")
        github_client.get_repo_info("owner", "repo")
    assert mock.call_count == 1


def test_get_repo_info_caches_negative_lookup():
    import urllib.error
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError("u", 404, "x", {}, None),
    ) as mock:
        github_client.get_repo_info("owner", "missing")
        github_client.get_repo_info("owner", "missing")
    assert mock.call_count == 1


def test_get_repo_info_returns_rate_limited_sentinel():
    import urllib.error
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            "u", 403, "rate limited",
            {"X-RateLimit-Remaining": "0"},
            None,
        ),
    ):
        info = github_client.get_repo_info("owner", "repo")
    assert info is github_client.RATE_LIMITED


def test_get_repo_info_does_not_cache_rate_limited():
    import urllib.error
    err = urllib.error.HTTPError(
        "u", 403, "rate limited", {"X-RateLimit-Remaining": "0"}, None,
    )
    with patch("urllib.request.urlopen", side_effect=err) as mock:
        github_client.get_repo_info("owner", "repo")
        github_client.get_repo_info("owner", "repo")
    assert mock.call_count == 2


def test_head_blob_200_returns_true():
    with patch("urllib.request.urlopen", return_value=_fake_resp(200)):
        assert github_client.head_blob("owner", "repo", "main", "src/a.py") is True


def test_head_blob_404_returns_false():
    import urllib.error
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError("u", 404, "x", {}, None),
    ):
        assert github_client.head_blob("owner", "repo", "main", "src/missing.py") is False


def test_head_blob_uses_HEAD_method():
    captured = {}

    def fake_urlopen(req, **kw):
        captured["method"] = req.get_method()
        return _fake_resp(200)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        github_client.head_blob("owner", "repo", "main", "src/a.py")
    assert captured["method"] == "HEAD"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
bash tests/run-daemon-tests.sh -k test_github_client -v 2>&1 | tee logs/plan-step.log
```

Expected: ImportError for `daemon.github_client`.

- [ ] **Step 3: Implement `daemon/github_client.py`**

```python
"""Minimal GitHub HTTP client used by files_md for default-branch + blob verification.

Process-lifetime in-memory cache. Unauthenticated requests (60/hr per IP) are
plenty for typical workshop traffic; we degrade gracefully on rate limits.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Final

import certifi

from daemon import log as _log

_NAME = "github"
_TIMEOUT_S = 3.0
_USER_AGENT = "TrainingAssistant/1.0"


@dataclass(frozen=True)
class RepoInfo:
    default_branch: str


class _Sentinel:
    pass


RATE_LIMITED: Final = _Sentinel()

# Cache: key=(owner, repo). Values:
#   RepoInfo  → public, default_branch known.
#   None      → known private/404 (negative cache, never re-queried).
#   missing key → unknown.
# RATE_LIMITED responses are NOT cached (so we retry on next event).
_REPO_CACHE: dict[tuple[str, str], RepoInfo | None] = {}


def reset_cache() -> None:
    _REPO_CACHE.clear()


def _ssl_ctx():
    return ssl.create_default_context(cafile=certifi.where())


def _is_rate_limited(err: urllib.error.HTTPError) -> bool:
    if err.code != 403:
        return False
    remaining = err.headers.get("X-RateLimit-Remaining") if err.headers else None
    return remaining == "0"


def get_repo_info(owner: str, repo: str) -> RepoInfo | None | _Sentinel:
    """Look up the repo. Returns:
       - RepoInfo on success (public)
       - None for private/missing (negative-cached)
       - RATE_LIMITED on rate-limit (not cached; caller may degrade gracefully)
    """
    key = (owner, repo)
    if key in _REPO_CACHE:
        return _REPO_CACHE[key]

    url = f"https://api.github.com/repos/{owner}/{repo}"
    req = urllib.request.Request(
        url, method="GET",
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S, context=_ssl_ctx()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        branch = str(data.get("default_branch") or "").strip() or "main"
        info = RepoInfo(default_branch=branch)
        _REPO_CACHE[key] = info
        return info
    except urllib.error.HTTPError as err:
        if _is_rate_limited(err):
            _log.warn(_NAME, f"rate-limited on /repos/{owner}/{repo}")
            return RATE_LIMITED
        if err.code in (404, 403):
            _REPO_CACHE[key] = None
            return None
        _log.error(_NAME, f"repo lookup {owner}/{repo} failed: {err}")
        _REPO_CACHE[key] = None
        return None
    except Exception as exc:  # noqa: BLE001
        _log.error(_NAME, f"repo lookup {owner}/{repo} crashed: {exc}")
        _REPO_CACHE[key] = None
        return None


def head_blob(owner: str, repo: str, branch: str, path: str) -> bool:
    """HEAD the GitHub blob page. Returns True iff 200."""
    url = f"https://github.com/{owner}/{repo}/blob/{branch}/{path}"
    req = urllib.request.Request(
        url, method="HEAD",
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S, context=_ssl_ctx()) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as err:
        return 200 <= err.code < 300
    except Exception:  # noqa: BLE001
        return False


def build_blob_url(owner: str, repo: str, branch: str, path: str) -> str:
    return f"https://github.com/{owner}/{repo}/blob/{branch}/{path}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
bash tests/run-daemon-tests.sh -k test_github_client -v 2>&1 | tee logs/plan-step.log
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add daemon/github_client.py tests/daemon/test_github_client.py
git commit -m "feat(daemon): github_client — repo info + blob HEAD with caching"
```

---

## Task 3: `files_md.record_file_opened` — full ingestion logic

Wire the parser + GitHub client into a single entry point that records one file-open event.

**Files:**
- Modify: `daemon/files_md.py`
- Modify: `tests/daemon/test_files_md.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/daemon/test_files_md.py`:

```python
import datetime as _dt
from unittest.mock import patch

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
    fixed = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))

    class _D:
        @classmethod
        def now(cls, tz=None):
            return fixed if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(files_md, "_utcnow_iso", lambda: iso)


def test_record_unknown_repo_public_with_valid_blob(session_folder, monkeypatch):
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    with patch.object(github_client, "get_repo_info", return_value=github_client.RepoInfo(default_branch="main")), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened(
            url="https://github.com/owner/repo.git",
            branch="feature/x",
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
            branch="main",
            file_path="src/missing.py",
        )
    text = (session_folder / "files.md").read_text()
    assert "- missing.py <!-- ts:2026-05-27T10:01:00Z reason:blob-404 -->" in text


def test_record_private_repo_writes_nothing(session_folder, monkeypatch):
    with patch.object(github_client, "get_repo_info", return_value=None):
        files_md.record_file_opened(
            url="https://github.com/owner/private",
            branch="main",
            file_path="src/a.py",
        )
    assert not (session_folder / "files.md").exists()


def test_record_rate_limited_on_unknown_repo_drops_event(session_folder, monkeypatch):
    """Privacy rule: never list a repo we haven't verified as public."""
    with patch.object(github_client, "get_repo_info", return_value=github_client.RATE_LIMITED):
        files_md.record_file_opened(
            url="https://github.com/owner/unknown",
            branch="main",
            file_path="src/a.py",
        )
    assert not (session_folder / "files.md").exists()


def test_record_rate_limited_on_known_public_repo_writes_unlinked(session_folder, monkeypatch):
    """If the repo is already in files.md (= already verified public), rate-limit
    on a subsequent file event still emits the entry — unlinked because we can't
    HEAD the blob either."""
    # Seed an existing entry so the repo is in files.md
    _freeze_now(monkeypatch, "2026-05-27T09:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened("https://github.com/owner/repo", "main", "src/first.py")

    # Now hit rate-limit on a second file in the same repo
    _freeze_now(monkeypatch, "2026-05-27T10:02:00Z")
    with patch.object(github_client, "get_repo_info", return_value=github_client.RATE_LIMITED):
        files_md.record_file_opened("https://github.com/owner/repo", "main", "src/second.py")
    text = (session_folder / "files.md").read_text()
    assert "- [first.py](https://github.com/owner/repo/blob/main/src/first.py)" in text
    assert "- second.py <!-- ts:2026-05-27T10:02:00Z reason:rate-limited -->" in text


def test_record_dedup_same_basename_skips(session_folder, monkeypatch):
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened("https://github.com/owner/repo", "main", "src/a.py")
        _freeze_now(monkeypatch, "2026-05-27T10:05:00Z")
        files_md.record_file_opened("https://github.com/owner/repo", "main", "src/a.py")
    text = (session_folder / "files.md").read_text()
    assert text.count("- [a.py]") == 1
    assert "ts:2026-05-27T10:00:00Z" in text  # original ts preserved
    assert "ts:2026-05-27T10:05:00Z" not in text


def test_record_collision_downgrades_to_unlinked(session_folder, monkeypatch):
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened("https://github.com/owner/repo", "main", "src/foo/utils.py")
        _freeze_now(monkeypatch, "2026-05-27T10:05:00Z")
        files_md.record_file_opened("https://github.com/owner/repo", "main", "src/bar/utils.py")
    text = (session_folder / "files.md").read_text()
    assert text.count("utils.py") == 1
    assert "- utils.py <!-- ts:2026-05-27T10:00:00Z reason:ambiguous -->" in text
    assert "[utils.py]" not in text  # link stripped


def test_record_empty_path_writes_unlinked_no_path(session_folder, monkeypatch):
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "head_blob", return_value=True) as head:
        files_md.record_file_opened("https://github.com/owner/repo", "main", "")
    head.assert_not_called()
    # Empty path → no basename — event dropped silently. files.md should not be created.
    assert not (session_folder / "files.md").exists()


def test_record_non_github_host_dropped(session_folder, monkeypatch):
    with patch.object(github_client, "get_repo_info") as info:
        files_md.record_file_opened("https://gitlab.com/owner/repo", "main", "src/a.py")
    info.assert_not_called()
    assert not (session_folder / "files.md").exists()


def test_repo_url_canonicalisation(session_folder, monkeypatch):
    """Trailing .git and trailing / both removed before storing."""
    _freeze_now(monkeypatch, "2026-05-27T10:00:00Z")
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.record_file_opened("https://github.com/owner/repo.git/", "main", "src/a.py")
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
bash tests/run-daemon-tests.sh -k test_files_md -v 2>&1 | tee logs/plan-step.log
```

Expected: many failures referencing missing `record_file_opened`, `_get_active_session_folder`, `_utcnow_iso`.

- [ ] **Step 3: Implement `record_file_opened` and helpers**

Append to `daemon/files_md.py` (do NOT touch the existing skeleton):

```python
from datetime import datetime, timezone
from urllib.parse import urlparse

from daemon import github_client
from daemon import log as _log

_NAME = "files_md"
_FILENAME = "files.md"


def _get_active_session_folder() -> Path | None:
    # Indirection so tests can monkeypatch.
    from daemon.misc.content_files import get_active_session_folder
    return get_active_session_folder()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_repo_url(url: str) -> str | None:
    """Return canonical https://github.com/OWNER/REPO or None if not github.com."""
    parsed = urlparse(url)
    if parsed.netloc.lower() != "github.com":
        return None
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    path = path.strip("/")
    parts = path.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None
    return f"https://github.com/{parts[0]}/{parts[1]}"


def _owner_repo(canonical_url: str) -> tuple[str, str]:
    parts = canonical_url.rsplit("/", 2)
    return parts[-2], parts[-1]


def _load_doc(folder: Path) -> Doc:
    target = folder / _FILENAME
    if not target.exists():
        return Doc()
    try:
        return Doc.parse(target.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _log.error(_NAME, f"parse {target} failed: {exc}; starting fresh")
        return Doc()


def _save_doc(folder: Path, doc: Doc) -> None:
    atomic_write(folder / _FILENAME, doc.render())


def record_file_opened(url: str, branch: str, file_path: str) -> None:
    """Process one addon git_file_opened event for the active session.

    Pipeline:
      1. Drop non-github.com hosts.
      2. Drop empty file paths.
      3. Resolve repo: cache hit, GitHub API, or rate-limited.
         - Private/missing repo → drop event entirely.
      4. Compute basename. Dedup by (repo, basename).
      5. If new entry: verify blob against default branch; write linked or unlinked.
      6. If existing linked entry with different path → downgrade to unlinked (ambiguous).
    """
    folder = _get_active_session_folder()
    if folder is None:
        return

    canonical = _canonical_repo_url(url)
    if canonical is None:
        return

    if not file_path or not file_path.strip() or file_path == "(none)":
        return

    basename = file_path.rsplit("/", 1)[-1].strip()
    if not basename:
        return

    owner, repo = _owner_repo(canonical)
    info = github_client.get_repo_info(owner, repo)

    if info is None:
        # Private or 404 — never list.
        return

    rate_limited = info is github_client.RATE_LIMITED

    doc = _load_doc(folder)
    repo_obj = doc.find_repo(canonical)

    if rate_limited:
        # Privacy rule: only emit if the repo is ALREADY in files.md (= previously
        # verified public). Otherwise we cannot prove it's public — drop the event.
        if repo_obj is None:
            return
        default_branch = repo_obj.default_branch
    else:
        default_branch = info.default_branch  # type: ignore[union-attr]
        if repo_obj is None:
            repo_obj = Repo(url=canonical, name=repo, default_branch=default_branch)
            doc.repos.append(repo_obj)

    # Dedup / collision
    existing = next((e for e in repo_obj.entries if e.basename == basename), None)
    if existing is not None:
        if existing.blob_url is None:
            return  # already unlinked, no upgrades
        if existing.path == file_path:
            return  # exact same file already linked
        # Different path under same basename → collision downgrade
        existing.blob_url = None
        existing.path = None
        existing.reason = "ambiguous"
        _save_doc(folder, doc)
        return

    # New entry
    ts = _utcnow_iso()
    if rate_limited:
        repo_obj.entries.append(
            Entry(basename=basename, blob_url=None, path=None, ts=ts, reason="rate-limited")
        )
        _save_doc(folder, doc)
        return

    blob_url = github_client.build_blob_url(owner, repo, default_branch, file_path)
    if github_client.head_blob(owner, repo, default_branch, file_path):
        repo_obj.entries.append(
            Entry(basename=basename, blob_url=blob_url, path=file_path, ts=ts, reason=None)
        )
    else:
        repo_obj.entries.append(
            Entry(basename=basename, blob_url=None, path=None, ts=ts, reason="blob-404")
        )
    _save_doc(folder, doc)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
bash tests/run-daemon-tests.sh -k test_files_md -v 2>&1 | tee logs/plan-step.log
```

Expected: all `test_files_md.py` tests pass.

- [ ] **Step 5: Commit**

```bash
git add daemon/files_md.py tests/daemon/test_files_md.py
git commit -m "feat(daemon): files_md.record_file_opened — verify + dedup + downgrade"
```

---

## Task 4: Migration from `session-state.json` `git_repos`

Convert legacy state on first read/write. Idempotent.

**Files:**
- Modify: `daemon/files_md.py`
- Modify: `tests/daemon/test_files_md.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/daemon/test_files_md.py`:

```python
import json


def _write_session_json(folder: Path, payload: dict) -> Path:
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
         patch.object(github_client, "head_blob", return_value=True):
        files_md.migrate_session_if_needed(session_folder)

    md = (session_folder / "files.md").read_text()
    assert "## [repo](https://github.com/owner/repo) <!-- default_branch:main -->" in md
    assert "[a.py]" in md and "[b.py]" in md

    js = json.loads((session_folder / "session-state.json").read_text())
    assert "git_repos" not in js


def test_migration_idempotent_when_files_md_exists(session_folder, monkeypatch):
    (session_folder / "files.md").write_text("# Files opened this session\n\nNo files opened yet\n")
    _write_session_json(session_folder, {"git_repos": [
        {"url": "https://github.com/owner/repo", "branch": "main", "files": ["src/a.py"], "file_urls": {}},
    ]})
    with patch.object(github_client, "get_repo_info") as info:
        files_md.migrate_session_if_needed(session_folder)
    info.assert_not_called()
    # session-state.json still untouched if files.md was already present
    js = json.loads((session_folder / "session-state.json").read_text())
    assert "git_repos" in js


def test_migration_no_op_when_no_git_repos(session_folder, monkeypatch):
    _write_session_json(session_folder, {"mode": "workshop"})
    with patch.object(github_client, "get_repo_info") as info:
        files_md.migrate_session_if_needed(session_folder)
    info.assert_not_called()
    assert not (session_folder / "files.md").exists()


def test_migration_collisions_downgrade_naturally(session_folder, monkeypatch):
    _write_session_json(session_folder, {
        "git_repos": [
            {
                "url": "https://github.com/owner/repo",
                "branch": "main",
                "files": ["src/foo/utils.py", "src/bar/utils.py"],
                "file_urls": {},
            },
        ],
    })
    info = github_client.RepoInfo(default_branch="main")
    with patch.object(github_client, "get_repo_info", return_value=info), \
         patch.object(github_client, "head_blob", return_value=True):
        files_md.migrate_session_if_needed(session_folder)
    text = (session_folder / "files.md").read_text()
    assert text.count("utils.py") == 1
    assert "reason:ambiguous" in text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
bash tests/run-daemon-tests.sh -k "test_migration" -v 2>&1 | tee logs/plan-step.log
```

Expected: AttributeError — no `migrate_session_if_needed`.

- [ ] **Step 3: Implement migration**

Append to `daemon/files_md.py`:

```python
import json as _json


def migrate_session_if_needed(folder: Path) -> None:
    """One-shot migration: convert session-state.json `git_repos` to files.md and remove the key.

    No-op if files.md already exists (so we never re-migrate or overwrite live state).
    No-op if session-state.json has no git_repos.
    """
    target = folder / _FILENAME
    if target.exists():
        return

    js_path = folder / "session-state.json"
    if not js_path.exists():
        return

    try:
        payload = _json.loads(js_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _log.error(_NAME, f"migration: failed to read {js_path}: {exc}")
        return

    repos = payload.get("git_repos") if isinstance(payload, dict) else None
    if not repos:
        return

    # Temporarily redirect _get_active_session_folder so record_file_opened writes here.
    # Use direct passes instead of monkey-patch — call internal helper.
    for repo_entry in repos:
        if not isinstance(repo_entry, dict):
            continue
        url = repo_entry.get("url", "")
        files = repo_entry.get("files", []) or []
        for f in files:
            if not isinstance(f, str):
                continue
            _record_into_folder(folder, url, f)

    # Strip the key and re-save
    payload.pop("git_repos", None)
    js_path.write_text(_json.dumps(payload, indent=2), encoding="utf-8")
    _log.info(_NAME, f"migrated {len(repos)} repo(s) for session {folder.name}")


def _record_into_folder(folder: Path, url: str, file_path: str) -> None:
    """Like record_file_opened but takes an explicit folder (used by migration)."""
    canonical = _canonical_repo_url(url)
    if canonical is None:
        return
    if not file_path or not file_path.strip() or file_path == "(none)":
        return
    basename = file_path.rsplit("/", 1)[-1].strip()
    if not basename:
        return

    owner, repo = _owner_repo(canonical)
    info = github_client.get_repo_info(owner, repo)
    if info is None:
        return
    rate_limited = info is github_client.RATE_LIMITED

    doc = _load_doc(folder)
    repo_obj = doc.find_repo(canonical)
    if rate_limited:
        if repo_obj is None:
            return
        default_branch = repo_obj.default_branch
    else:
        default_branch = info.default_branch  # type: ignore[union-attr]
        if repo_obj is None:
            repo_obj = Repo(url=canonical, name=repo, default_branch=default_branch)
            doc.repos.append(repo_obj)

    existing = next((e for e in repo_obj.entries if e.basename == basename), None)
    if existing is not None:
        if existing.blob_url is None:
            return
        if existing.path == file_path:
            return
        existing.blob_url = None
        existing.path = None
        existing.reason = "ambiguous"
        _save_doc(folder, doc)
        return

    ts = _utcnow_iso()
    if rate_limited:
        repo_obj.entries.append(
            Entry(basename=basename, blob_url=None, path=None, ts=ts, reason="rate-limited")
        )
        _save_doc(folder, doc)
        return

    blob_url = github_client.build_blob_url(owner, repo, default_branch, file_path)
    if github_client.head_blob(owner, repo, default_branch, file_path):
        repo_obj.entries.append(
            Entry(basename=basename, blob_url=blob_url, path=file_path, ts=ts, reason=None)
        )
    else:
        repo_obj.entries.append(
            Entry(basename=basename, blob_url=None, path=None, ts=ts, reason="blob-404")
        )
    _save_doc(folder, doc)
```

Also refactor `record_file_opened` to delegate to `_record_into_folder`, so we have a single implementation. Replace the body of `record_file_opened` with:

```python
def record_file_opened(url: str, branch: str, file_path: str) -> None:
    folder = _get_active_session_folder()
    if folder is None:
        return
    migrate_session_if_needed(folder)
    _record_into_folder(folder, url, file_path)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
bash tests/run-daemon-tests.sh -k test_files_md -v 2>&1 | tee logs/plan-step.log
```

Expected: all `test_files_md.py` tests still pass + 4 new migration tests pass.

- [ ] **Step 5: Commit**

```bash
git add daemon/files_md.py tests/daemon/test_files_md.py
git commit -m "feat(daemon): files_md migration from session-state.json git_repos"
```

---

## Task 5: REST endpoint `GET /api/participant/files-md`

Mirror the `summary` endpoint pattern. Returns JSON `{raw_markdown, updated_at}` with HTML comments stripped.

**Files:**
- Modify: `daemon/misc/router.py`
- Create: `tests/daemon/test_files_md_router.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/daemon/test_files_md_router.py
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from daemon import files_md


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    from daemon.app import build_app  # adjust import if needed; matches existing tests

    folder = tmp_path / "session"
    folder.mkdir()
    monkeypatch.setattr(files_md, "_get_active_session_folder", lambda: folder)
    monkeypatch.setattr(
        "daemon.misc.content_files.get_active_session_folder", lambda: folder
    )

    app = build_app()
    yield TestClient(app), folder


def test_files_md_endpoint_empty(client):
    tc, _folder = client
    resp = tc.get("/api/participant/files-md")
    assert resp.status_code == 200
    body = resp.json()
    assert body["raw_markdown"] == files_md.EMPTY_STATE
    assert body["updated_at"] is None


def test_files_md_endpoint_returns_sanitized_markdown(client, monkeypatch):
    tc, folder = client
    (folder / "files.md").write_text(
        "# Files opened this session\n\n"
        "## [repo](https://github.com/owner/repo) <!-- default_branch:main -->\n\n"
        "- [a.py](https://github.com/owner/repo/blob/main/src/a.py) <!-- ts:2026-05-27T10:00:00Z path:src/a.py -->\n",
        encoding="utf-8",
    )
    resp = tc.get("/api/participant/files-md")
    assert resp.status_code == 200
    body = resp.json()
    assert "<!--" not in body["raw_markdown"]
    assert "## [repo](https://github.com/owner/repo)" in body["raw_markdown"]
    assert body["updated_at"] is not None
```

If `build_app` is not the correct factory in this project, look at `tests/daemon/test_misc_router.py` for the pattern used to construct a test client there and copy it.

- [ ] **Step 2: Verify test discovery / find correct app factory**

```bash
grep -n "build_app\|FastAPI\|TestClient" tests/daemon/test_misc_router.py daemon/__main__.py daemon/app.py 2>/dev/null | head
```

If `build_app` doesn't exist, adapt the fixture to import the FastAPI app object directly the same way `test_misc_router.py` does, then proceed.

- [ ] **Step 3: Run tests to verify they fail**

```bash
bash tests/run-daemon-tests.sh -k test_files_md_router -v 2>&1 | tee logs/plan-step.log
```

Expected: 404 on `/api/participant/files-md` for both tests.

- [ ] **Step 4: Add the endpoint to `daemon/misc/router.py`**

In `daemon/misc/router.py`, after the `get_summary` endpoint, add:

```python
from daemon import files_md as _files_md


class FilesMdResponse(BaseModel):
    raw_markdown: str
    updated_at: str | None


@participant_router.get("/files-md", response_model=FilesMdResponse)
async def get_files_md():
    """Return the per-session files.md content with HTML comments stripped."""
    from daemon.misc.content_files import get_active_session_folder
    folder = get_active_session_folder()
    if folder is None:
        return FilesMdResponse(raw_markdown=_files_md.EMPTY_STATE, updated_at=None)
    _files_md.migrate_session_if_needed(folder)
    target = folder / "files.md"
    if not target.exists():
        return FilesMdResponse(raw_markdown=_files_md.EMPTY_STATE, updated_at=None)
    raw = target.read_text(encoding="utf-8")
    sanitized = _files_md.sanitize_for_wire(raw)
    from datetime import datetime, timezone
    mtime_ns = target.stat().st_mtime_ns
    iso = datetime.fromtimestamp(mtime_ns / 1e9, tz=timezone.utc).isoformat()
    return FilesMdResponse(raw_markdown=sanitized, updated_at=iso)
```

If `BaseModel` isn't already imported at the top of `daemon/misc/router.py`, add `from pydantic import BaseModel`.

- [ ] **Step 5: Run tests to verify they pass**

```bash
bash tests/run-daemon-tests.sh -k test_files_md_router -v 2>&1 | tee logs/plan-step.log
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add daemon/misc/router.py tests/daemon/test_files_md_router.py
git commit -m "feat(daemon): GET /api/participant/files-md returns sanitized markdown"
```

---

## Task 6: Wire addon ingestion → `files_md.record_file_opened`

Swap the call site in `addon_bridge_client.py`. Keep behaviour identical for the read path (still satisfies the legacy `git_files_count` / `last_git_url` users until Task 7 removes them).

**Files:**
- Modify: `daemon/addon_bridge_client.py:166-180`
- Modify: `tests/daemon/test_daemon.py` *(or wherever the addon-event handler is tested — search for `git_file_opened` in tests)*

- [ ] **Step 1: Find current test coverage**

```bash
grep -rn "git_file_opened\|accumulate_git_file" tests/ 2>&1 | head
```

- [ ] **Step 2: Add a new test for the swap**

Append to `tests/daemon/test_daemon.py` (or create `tests/daemon/test_addon_bridge_client.py` if no matching test exists today):

```python
def test_addon_git_file_opened_calls_files_md(monkeypatch):
    from daemon import files_md
    calls: list[tuple] = []
    monkeypatch.setattr(
        files_md, "record_file_opened",
        lambda url, file_path: calls.append((url, file_path)),
    )

    from daemon.addon_bridge_client import _handle_addon_message  # see Step 3
    _handle_addon_message({
        "type": "git_file_opened",
        "url": "https://github.com/owner/repo",
        "branch": "main",
        "file": "src/a.py",
    })

    assert calls == [("https://github.com/owner/repo", "src/a.py")]
```

- [ ] **Step 3: Refactor & swap the call site**

In `daemon/addon_bridge_client.py`, extract the inline `elif data.get("type") == "git_file_opened":` branch into a small module-level function `_handle_git_file_opened(data: dict) -> None` so it's testable. Replace the inline branch with a call to it (and a similar `_handle_addon_message(data)` dispatcher if convenient — adapt to existing style).

New `_handle_git_file_opened` body:

```python
def _handle_git_file_opened(data: dict) -> None:
    from daemon import files_md
    url = data.get("url", "")
    branch = data.get("branch", "")
    file_path = data.get("file", "")
    if not url or not file_path:
        return
    files_md.record_file_opened(url, branch, file_path)
    log.debug(_NAME, f"← git {url.split('/')[-1]}:{branch} {file_path}")
```

Replace the call inside the WS loop:

```python
elif data.get("type") == "git_file_opened":
    _handle_git_file_opened(data)
```

(Drop the existing `from daemon.participant.state import participant_state` import inside that branch — no longer needed there.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
bash tests/run-daemon-tests.sh -k "addon or git_file" -v 2>&1 | tee logs/plan-step.log
```

Expected: new test passes; no regressions.

- [ ] **Step 5: Commit**

```bash
git add daemon/addon_bridge_client.py tests/daemon/
git commit -m "feat(daemon): route addon git_file_opened to files_md.record_file_opened"
```

---

## Task 7: Remove dead code

Now that `files_md` is the sole writer, strip the legacy storage paths so the codebase has one truth.

**Files:**
- Modify: `daemon/participant/state.py`
- Modify: `daemon/participant/router.py`
- Modify: `daemon/openapi_contract_metadata.py:28-31`

- [ ] **Step 1: Update tests that referenced the legacy fields**

Search for callers:

```bash
grep -rn "GitRepoActivity\|accumulate_git_file\|git_files_count\|last_git_url\|/git-activity" \
  daemon/ tests/ static/ 2>/dev/null | grep -v __pycache__
```

For each test reference, remove the assertions or rewrite to assert via `files.md` content. Production callers besides the addon bridge are already gone after Task 6.

- [ ] **Step 2: Strip `daemon/participant/state.py`**

Remove `GitRepoActivity` class, `git_repos: list[GitRepoActivity] = []` field, `accumulate_git_file(...)` method, and the `git_repos` handling in `sync_from_restore` (lines 144-155) / `snapshot` (the `"git_repos": ...` line) / `reset` (`self.git_repos.clear()`).

- [ ] **Step 3: Strip `daemon/participant/router.py`**

- Remove the `from daemon.participant.state import GitRepoActivity, participant_state` import — change to `from daemon.participant.state import participant_state`.
- Remove `GitActivityResponse` class.
- Remove the `@router.get("/git-activity", ...)` endpoint.
- Remove `git_files_count: int` from `ParticipantStateResponse`.
- Remove the `"git_files_count": sum(...)` line in `get_participant_state`.
- Remove the `"last_git_url": ps.git_repos[-1].url ...` line in `get_participant_state`.

- [ ] **Step 4: Strip `daemon/openapi_contract_metadata.py`**

Delete lines 30-31:

```python
    if path == "/api/participant/git-activity":
        return "activity"
```

- [ ] **Step 5: Run the full daemon test suite**

```bash
bash tests/run-daemon-tests.sh 2>&1 | tee logs/plan-step.log
```

Expected: all green. If a test fails because it referenced `git_repos` / `git_files_count` / `last_git_url`, delete those assertions — the field genuinely no longer exists.

- [ ] **Step 6: Commit**

```bash
git add daemon/participant/state.py daemon/participant/router.py daemon/openapi_contract_metadata.py tests/
git commit -m "refactor(daemon): remove legacy git_repos storage and /git-activity endpoint"
```

---

## Task 8: Participant UI — nav entry + `loadFilesMd()`

Replace the collapsible `gitrepos` block with a single non-collapsible `Files` entry.

**Files:**
- Modify: `static/participant.html:535-549` (nav block)
- Modify: `static/participant.html:1633-1688` (toggleRepos/openRepos/closeRepos)
- Modify: `static/participant.html` (new `#files-content` pane + `loadFilesMd()` function near `loadSummary()`)

- [ ] **Step 1: Replace the nav entry**

Replace lines 535-549 (the `<div>...gitrepos...</div>` block) with:

```html
<a data-nav="files" onclick="showView('files')" class="nav-item rounded-full px-2 py-2 flex items-center gap-3 transition-all cursor-pointer">
  <span class="material-symbols-outlined" style="font-size:22px;line-height:1;flex-shrink-0">commit</span>
  <span class="text-base">Files</span>
</a>
```

- [ ] **Step 2: Remove the obsolete JS functions**

Delete `openRepos`, `closeRepos`, `toggleRepos`, and any `_setCodeBadge(...)` calls that target `#code-badge`. Also remove the `_codeBadge*` / `_setCodeBadge` helper if it's only used by repo rendering (grep first).

```bash
grep -n "toggleRepos\|openRepos\|closeRepos\|_setCodeBadge\|code-badge\|repos-content\|repos-arrow\|repos-list" static/participant.html
```

For each match: either delete or leave the line alone if it serves another feature.

- [ ] **Step 3: Find the spot to add the new pane**

Find the existing `<div id="summary-scroll">` / `<div id="summary-content">` block in `static/participant.html` (search `id="summary-content"`). Add a sibling block for files:

```html
<div id="files-scroll" class="overflow-y-auto h-full" style="display:none">
  <div id="files-content" class="px-4 py-3 max-w-3xl mx-auto"></div>
</div>
```

(Match the surrounding container's class set so layout is consistent. If summary uses different wrapper classes, mirror them.)

- [ ] **Step 4: Add `loadFilesMd()` next to `loadSummary()`**

Just after `loadSummary()` ends (around line 3710), add:

```js
var _filesDirty = true;
var _filesRawMarkdown = '';

async function loadFilesMd() {
  if (!_filesDirty) return;
  _filesDirty = false;
  const el = document.getElementById('files-content');
  el.textContent = 'Loading…';
  try {
    const data = await fetch(`/${_sessionId}/api/participant/files-md`).then(r => r.ok ? r.json() : Promise.reject('not found'));
    const md = (data && data.raw_markdown) || '';
    _filesRawMarkdown = md;
    if (md.trim()) {
      var _renderer = new marked.Renderer();
      _renderer.link = function(href, title, text) {
        var t = title ? ' title="' + title + '"' : '';
        return '<a href="' + href + '" target="_blank" rel="noopener"' + t + '>'
          + text
          + '<span class="material-symbols-outlined" style="font-size:0.85em;vertical-align:middle;margin-left:2px;opacity:0.7">open_in_new</span>'
          + '</a>';
      };
      el.innerHTML = marked.parse(md, { renderer: _renderer });
    } else {
      el.textContent = 'No files opened yet.';
    }
  } catch (e) {
    el.textContent = 'Failed to load files.';
    _filesDirty = true;
  }
}
```

- [ ] **Step 5: Wire `showView('files')`**

Find `showView` (search `function showView`) and add a branch for `files`. Pattern follows the existing `summary` branch — show `#files-scroll`, hide others, call `loadFilesMd()`. Mark `_filesDirty = true` whenever a fresh session loads (the participant-state response payload no longer has `git_files_count`, so the previous "dirty bit on count change" mechanism is gone — instead, set `_filesDirty = true` on each `showView('files')` entry to force a refetch).

Replace `_filesDirty = false` initialisation with `var _filesDirty = true` (already done above) and inside `showView('files')`:

```js
} else if (view === 'files') {
  document.querySelectorAll('[data-view-scroll]').forEach(...);  // copy current pattern
  // … show #files-scroll, hide others …
  _filesDirty = true;
  loadFilesMd();
}
```

Adapt to the actual `showView` body — copy the summary branch structure verbatim and swap identifiers.

- [ ] **Step 6: Sanity-check in a browser**

Start the dev server and verify the new nav entry works (the empty-state text "No files opened yet" should render):

```bash
python3 -m daemon &
DAEMON_PID=$!
sleep 4
open http://localhost:8081/  # or curl-check the new endpoint
# After verifying, kill:
kill $DAEMON_PID
```

Per project rule: take a screenshot of the participant page showing the new "Files" nav entry + empty state, and attach to the commit.

- [ ] **Step 7: Commit**

```bash
git add static/participant.html
git commit -m "feat(participant): replace Repos nav with non-collapsible Files entry"
```

---

## Task 9: Regenerate OpenAPI snapshot + API.md

Per project rule: never edit `API.md` directly — regenerate from contracts.

**Files:**
- Modify: `docs/openapi.yaml` (regenerated)
- Modify: `API.md` (regenerated)
- Modify: `tests/daemon/test_api_contract.py` snapshot if it's a frozen snapshot

- [ ] **Step 1: Regenerate the OpenAPI doc**

Find the regeneration script — check the README / scripts directory:

```bash
ls scripts/ | grep -i openapi
grep -rn "openapi" scripts/ daemon/ 2>/dev/null | head
```

Run the regen command (likely `python3 scripts/generate_openapi.py` or `python3 -m daemon.openapi_dump`). Update `docs/openapi.yaml`.

- [ ] **Step 2: Regenerate `API.md`**

```bash
python3 scripts/generate_apis_md.py --output API.md
```

- [ ] **Step 3: Run the contract test**

```bash
bash tests/run-daemon-tests.sh -k test_api_contract -v 2>&1 | tee logs/plan-step.log
```

Expected: passes. If it asserts against an inline snapshot, update the snapshot in the same commit.

- [ ] **Step 4: Commit**

```bash
git add docs/openapi.yaml API.md tests/daemon/test_api_contract.py
git commit -m "docs(api): regenerate openapi + API.md after files-md endpoint swap"
```

---

## Task 10: Hermetic Docker E2E

Two participants + addon firing three file events (public-valid, public-invalid-path, private). Marked nightly.

**Files:**
- Create: `tests/docker/test_files_md_e2e.py`

- [ ] **Step 1: Skim existing docker tests for the patterns this project uses**

```bash
ls tests/docker/
cat tests/docker/conftest.py 2>/dev/null | head -50
```

Pick the closest existing test (e.g. the poll lifecycle test from commit `a7f37953`) as a template — it already sets up two participants.

- [ ] **Step 2: Write the test**

```python
# tests/docker/test_files_md_e2e.py
import pytest

pytestmark = pytest.mark.nightly


def test_files_md_two_participants_three_events(docker_stack, page_factory, github_stub):
    """
    Fires three GitFileOpenedMsg from the addon stub:
      a) public repo + valid path on default branch → linked bullet
      b) public repo + 404 blob path → unlinked bullet (reason hidden)
      c) private repo → no section, no bullets

    Both participants click "Files"; both see public repo with two bullets,
    private repo entirely absent, and no HTML comments in the network response.
    """
    github_stub.set_repo("victorrentea", "training-assistant", default_branch="master")
    github_stub.set_blob_status("victorrentea/training-assistant", "static/participant.html", 200)
    github_stub.set_blob_status("victorrentea/training-assistant", "totally/missing/path.py", 404)
    github_stub.set_repo("owner", "private", status=404)

    docker_stack.addon_send_git_file_opened(
        url="https://github.com/victorrentea/training-assistant",
        branch="feature/x",
        file="static/participant.html",
    )
    docker_stack.addon_send_git_file_opened(
        url="https://github.com/victorrentea/training-assistant",
        branch="feature/x",
        file="totally/missing/path.py",
    )
    docker_stack.addon_send_git_file_opened(
        url="https://github.com/owner/private",
        branch="main",
        file="some.py",
    )

    p1 = page_factory.participant()
    p2 = page_factory.participant()

    for p in (p1, p2):
        p.click('a[data-nav="files"]')
        p.wait_for_text('# Files opened this session', timeout=10)
        body = p.inner_html('#files-content')
        assert 'training-assistant' in body
        assert 'participant.html' in body
        assert 'path.py' in body
        assert 'owner/private' not in body
        # Verify the link presence (linked entry) and absence (unlinked entry)
        assert 'href="https://github.com/victorrentea/training-assistant/blob/master/static/participant.html"' in body
        # The 404'd file appears unlinked — no <a> tag wrapping it
        assert '<a' not in body.split('path.py')[0].rsplit('<li', 1)[-1]

    # Inspect the wire response — must contain no HTML comments
    raw = p1.fetch_text('/api/participant/files-md')
    assert '<!--' not in raw
```

If `github_stub` / `page_factory.participant` aren't existing fixtures, base on what exists in `tests/docker/conftest.py`. Adapt as needed but keep the assertions intact.

- [ ] **Step 3: Run the hermetic suite**

```bash
bash tests/docker/run-hermetic.sh -k test_files_md_two_participants_three_events -m nightly -s 2>&1 | tee logs/plan-step.log
```

Expected: passes inside Docker. (Memory rule: never declare hermetic tests done without running them in Docker.)

- [ ] **Step 4: Commit**

```bash
git add tests/docker/test_files_md_e2e.py
git commit -m "test(docker): files.md E2E — two participants, three addon events"
```

---

## Task 11: Full local feedback loop + pre-commit checks

Per project rule (`feedback_propose_feedback_loops`): run every feedback loop available.

- [ ] **Step 1: Full quick test suite**

```bash
bash tests/check-all.sh 2>&1 | tee logs/plan-step.log
```

Expected: all green. Fix anything that doesn't relate to files.md by referring back to the relevant task; for files.md-related failures, fix in this task and amend the appropriate prior commit if narrow.

- [ ] **Step 2: Pre-commit checklist (per `victor-skills:pre-commit-checklist` skill)**

```bash
# Lint, type, dead-code, secrets — as configured in pre-commit
git diff --stat HEAD~10..HEAD  # quick scan of the change set
```

- [ ] **Step 3: Verify no residual references**

```bash
grep -rn "git_repos\|GitRepoActivity\|accumulate_git_file\|git_files_count\|last_git_url\|/git-activity\|toggleRepos\|openRepos\|closeRepos\|repos-content\|code-badge" \
  daemon/ static/ tests/ railway/ docs/openapi.yaml API.md 2>/dev/null | grep -v __pycache__
```

Expected: empty (or only inside the spec file, which is fine).

---

## Task 12: Push to master + verify production

Per project rules: push after each task, but for this multi-task feature push all at once at the end. Then verify the live endpoint.

- [ ] **Step 1: Pull/rebase to be safe**

```bash
git fetch origin master
git rebase origin/master
```

Resolve conflicts if any. Re-run `bash tests/check-all.sh` if you rebased on top of new commits.

- [ ] **Step 2: Push**

```bash
git push origin master
```

- [ ] **Step 3: Wait for Railway redeploy**

```bash
sleep 60  # Railway auto-deploys in ~40-50s on push to master
```

- [ ] **Step 4: Confirm the new endpoint is live**

```bash
curl -s https://interact.victorrentea.ro/api/participant/files-md | head
```

Expected: JSON `{"raw_markdown":"# Files opened this session\n\nNo files opened yet\n","updated_at":null}` (the active session may be different; the shape is the contract).

- [ ] **Step 5: Confirm the old endpoint is gone**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://interact.victorrentea.ro/api/participant/git-activity
```

Expected: `404`.

(Memory rule: `daemon_code_timestamp` does NOT equal Railway redeploy. If 404 doesn't appear immediately, wait another 60s and retry.)

- [ ] **Step 6: Open the participant page in a real browser**

Open https://interact.victorrentea.ro/ in incognito, click "Files", verify rendering. If the active workshop has files, the list should be populated; otherwise the empty-state message appears.

- [ ] **Step 7: Screenshot proof**

Take a screenshot of the live participant view showing the new "Files" entry and rendered content. Attach to the final commit message (or paste in chat).

---

## Spec coverage recap

| Spec requirement | Task |
| --- | --- |
| `files.md` format + HTML comment metadata | Task 1, Task 3 |
| Public-repo-only via GitHub API | Task 2, Task 3 |
| Blob URL verification | Task 2, Task 3 |
| Dedup by (repo, basename) | Task 3 |
| Collision downgrade | Task 3 |
| Rate-limited handling | Task 2, Task 3 |
| Migration from session-state.json | Task 4 |
| `/api/participant/files-md` endpoint | Task 5 |
| HTML comment stripping on wire | Task 5 |
| Addon ingestion swap | Task 6 |
| Removal of legacy code | Task 7 |
| Participant UI: nav entry + main pane | Task 8 |
| OpenAPI + API.md regen | Task 9 |
| Hermetic E2E (two participants, three events) | Task 10 |
| Post-deploy production check | Task 12 |
