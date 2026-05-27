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
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from daemon import github_client
from daemon import log as _log

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
         - Rate-limited on unknown repo → drop event (privacy rule).
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
        # Privacy rule: only emit if the repo is ALREADY in files.md
        # (= previously verified public). Otherwise drop the event.
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
