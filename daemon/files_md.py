"""files.md — the canonical store of files opened during a session.

All feature state lives in the markdown file itself:
- Repo default branch cached in `<!-- default_branch:... -->` on the `##` heading.
- File first-open timestamp + path/reason cached in HTML comments on each bullet.

HTML comments are stripped before serving to participants — see `sanitize_for_wire`.
"""
from __future__ import annotations

import json as _json
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
                    # Link text is the full repo-relative path so participants
                    # see where the file lives (e.g. `src/main/java/Foo.java`)
                    # instead of just the bare basename.
                    parts.append(
                        f"- [{e.path}]({e.blob_url}) <!-- ts:{e.ts} path:{e.path} -->"
                    )
                else:
                    parts.append(
                        f"- {e.basename} <!-- ts:{e.ts} reason:{e.reason or 'no-path'} -->"
                    )
            parts.append("")
        text = "\n".join(parts).rstrip() + "\n"
        return text

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
                # `path:` in the trailing comment is authoritative — older files
                # rendered the link text as the basename, newer ones render the
                # full path, but the comment carries the canonical path either way.
                path = m.group("path")
                basename = path.rsplit("/", 1)[-1] if path else m.group("basename")
                current.entries.append(
                    Entry(
                        basename=basename,
                        blob_url=m.group("blob"),
                        path=path,
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
# Sentinel the macOS IDE addon sends when a project is open but no file is selected.
_ADDON_NO_FILE_SENTINEL = "(none)"
# Basenames the IDE addon occasionally reports that are not real files.
# Drop these events on ingestion AND prune any historical entries on load.
_NOISE_BASENAMES: frozenset[str] = frozenset({
    "✻",  # Claude Code spinner character that occasionally leaks through IntelliJ
})


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
    # Invariant: callers pass the exact output of _canonical_repo_url(...),
    # which always has the shape https://github.com/<owner>/<repo> (no trailing
    # slash, no .git suffix, both segments non-empty).
    parts = canonical_url.rsplit("/", 2)
    return parts[-2], parts[-1]


def _load_doc(folder: Path) -> Doc:
    target = folder / _FILENAME
    if not target.exists():
        return Doc()
    try:
        doc = Doc.parse(target.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _log.error(_NAME, f"parse {target} failed: {exc}; starting fresh")
        return Doc()
    changed = False
    if _strip_noise_entries(doc):
        _log.info(_NAME, f"pruned noise entries from {target.name}")
        changed = True
    if _upgrade_unlinked_entries(doc):
        _log.info(_NAME, f"upgraded previously-unlinked entries in {target.name}")
        changed = True
    if changed:
        _save_doc(folder, doc)
    return doc


def count_open_files(folder: Path | None) -> int:
    """Number of files recorded in the session's files.md (0 if none/absent).

    Pure read — parses the markdown without the prune/upgrade side effects of
    `_load_doc`, so it is cheap enough for the main-loop probe and `GET /state`.
    """
    if folder is None:
        return 0
    target = folder / _FILENAME
    if not target.exists():
        return 0
    try:
        doc = Doc.parse(target.read_text(encoding="utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return 0
    return sum(len(repo.entries) for repo in doc.repos)


def _strip_noise_entries(doc: Doc) -> bool:
    """Remove entries whose basename is a known noise token. Returns True if anything was stripped."""
    changed = False
    for repo in doc.repos:
        before = len(repo.entries)
        repo.entries = [e for e in repo.entries if e.basename not in _NOISE_BASENAMES]
        if len(repo.entries) != before:
            changed = True
    return changed


def _upgrade_unlinked_entries(doc: Doc) -> bool:
    """Retry path resolution for previously-unlinked entries via the (now-cached) repo tree.

    Skips entries flagged `ambiguous` — those have multiple matches in the tree by design.
    Returns True if any entry was upgraded to linked.
    """
    changed = False
    for repo_obj in doc.repos:
        owner, repo = _owner_repo(repo_obj.url)
        tree = github_client.get_repo_tree(owner, repo, repo_obj.default_branch)
        if tree is None or tree.truncated:
            continue
        for e in repo_obj.entries:
            if e.blob_url is not None:
                continue
            if e.reason == "ambiguous":
                continue
            matches = tree.paths_by_basename.get(e.basename, [])
            if len(matches) == 1:
                e.blob_url = github_client.build_blob_url(
                    owner, repo, repo_obj.default_branch, matches[0]
                )
                e.path = matches[0]
                e.reason = None
                changed = True
    return changed


def _save_doc(folder: Path, doc: Doc) -> None:
    atomic_write(folder / _FILENAME, doc.render())


def record_file_opened(url: str, file_path: str) -> None:
    """Process one addon git_file_opened event for the active session.

    The addon's reported `branch` is intentionally ignored — we always resolve
    against the repo's GitHub default branch so links never go stale.
    """
    folder = _get_active_session_folder()
    if folder is None:
        return
    migrate_session_if_needed(folder)
    _record_into_folder(folder, url, file_path)


def _record_into_folder(folder: Path, url: str, file_path: str) -> None:
    """Record one file event into an explicit session folder.

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
    canonical = _canonical_repo_url(url)
    if canonical is None:
        return

    if not file_path or not file_path.strip() or file_path == _ADDON_NO_FILE_SENTINEL:
        return

    basename = file_path.rsplit("/", 1)[-1].strip()
    if not basename:
        return
    if basename in _NOISE_BASENAMES:
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

    # Try tree-based resolution first
    tree = github_client.get_repo_tree(owner, repo, default_branch) if not rate_limited else None
    resolved_path: str | None = None
    reason: str | None = None

    if tree is not None and not tree.truncated:
        # Tree is authoritative
        if file_path in tree.paths:
            resolved_path = file_path
        else:
            basename_matches = tree.paths_by_basename.get(basename, [])
            if len(basename_matches) == 1:
                resolved_path = basename_matches[0]
            elif len(basename_matches) >= 2:
                reason = "ambiguous"
            else:
                reason = "not-in-repo"
    else:
        # Tree unavailable (rate-limited, truncated, network) — fall back to HEAD
        if not rate_limited and github_client.head_blob(owner, repo, default_branch, file_path):
            resolved_path = file_path
        elif rate_limited:
            reason = "rate-limited"
        else:
            reason = "blob-404"

    # Dedup / collision handling
    existing = next((e for e in repo_obj.entries if e.basename == basename), None)
    if existing is not None:
        if existing.blob_url is None:
            return  # already unlinked, no upgrades
        # If the resolution gives us a path and it matches existing → no-op
        if resolved_path is not None and existing.path == resolved_path:
            return
        # Collision downgrade: different path under same basename
        _log.info(
            _NAME,
            f"basename collision in {canonical}: '{basename}' "
            f"(was: {existing.path}, now: {resolved_path or file_path}) → downgrade to unlinked",
        )
        existing.blob_url = None
        existing.path = None
        existing.reason = "ambiguous"
        _save_doc(folder, doc)
        return

    # New entry
    ts = _utcnow_iso()
    if resolved_path is not None:
        blob_url = github_client.build_blob_url(owner, repo, default_branch, resolved_path)
        repo_obj.entries.append(
            Entry(basename=basename, blob_url=blob_url, path=resolved_path, ts=ts, reason=None)
        )
    else:
        repo_obj.entries.append(
            Entry(basename=basename, blob_url=None, path=None, ts=ts, reason=reason or "not-in-repo")
        )
    _save_doc(folder, doc)


def migrate_session_if_needed(folder: Path) -> None:
    """One-shot migration: convert session-state.json `git_repos` to files.md
    and remove the key.

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
