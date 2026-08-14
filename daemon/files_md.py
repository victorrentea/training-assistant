"""opened-files.md — the canonical store of files opened during a session.

All feature state lives in the markdown file itself:
- Each repo heading carries its most-recently-opened branch and its GitHub
  default branch in `<!-- branch:... default_branch:... -->`.
- Each entry carries its own branch, timestamp, and (for unlinked entries) a
  reason, all cached in an HTML comment on the bullet. The visible text is
  always the full repo-relative path (as link text, or bare for unlinked
  entries) — nothing is duplicated into the comment.

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
    reason: str | None = None   # "not-pushed" | "no-branch" | "rate-limited" | "unknown"


@dataclass
class Repo:
    url: str
    name: str
    default_branch: str
    branch: str                 # branch of the most recent open in this repo
    entries: list[Entry] = field(default_factory=list)

    def display_branch(self) -> str:
        """The branch shown beside the repo, and the baseline entries compare against.

        Not the most recent open: a single file opened on `main` used to
        re-label a repo whose whole session happened on a feature branch, and
        then every real entry grew a redundant ` · branch` chip. The branch most
        of the repo's files were opened on is what the heading is actually
        claiming, so count them; ties break toward the most recent open.
        """
        if not self.entries:
            return self.branch
        counts: dict[str, int] = {}
        for e in self.entries:
            counts[e.branch] = counts.get(e.branch, 0) + 1
        top = max(counts.values())
        tied = {b for b, c in counts.items() if c == top}
        if self.branch in tied:
            return self.branch
        for e in sorted(self.entries, key=lambda e: e.ts, reverse=True):
            if e.branch in tied:
                return e.branch
        return self.branch


@dataclass
class Doc:
    repos: list[Repo] = field(default_factory=list)

    def find_repo(self, url: str) -> Repo | None:
        for r in self.repos:
            if r.url == url:
                return r
        return None

    def render(self) -> str:
        # A repo whose every entry was dropped (e.g. legacy path-less entries
        # lost on migration) must not survive as a bare heading with nothing
        # under it — that reads as a real, empty repo to a participant.
        repos = [r for r in self.repos if r.entries]
        if not repos:
            return EMPTY_STATE
        with_date = _needs_date([e.ts for r in repos for e in r.entries])
        parts = [_TITLE, ""]
        for repo in repos:
            # Visible heading = the repo's dominant branch; the `branch:` comment
            # stays the most-recent one, which is what record/parse rely on.
            shown = repo.display_branch()
            parts.append(
                f"## [{repo.name}]({repo.url}) — branch `{shown}` "
                f"<!-- branch:{repo.branch} default_branch:{repo.default_branch} -->"
            )
            parts.append("")
            for e in repo.entries:
                parts.append(_render_entry(e, shown, with_date))
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
    # `e.ref` is None for entries migrated from a pre-`ref:` format that were
    # still linked (a `path:`-comment entry, e.g.) — fall back rather than
    # emit the literal string "ref:None", which parses back as text.
    tail = f"ref:{e.ref or 'default'}" if e.blob_url else f"reason:{e.reason or 'not-pushed'}"
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


def atomic_write(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


def sanitize_for_wire(text: str) -> str:
    return _RE_COMMENT.sub("", text)


_NAME = "files_md"
_FILENAME = "opened-files.md"


def session_filename() -> str:
    """Name of the on-disk artifact inside a session folder.

    Exposed so callers never hardcode the literal — two of them had drifted
    into their own copies of "files.md", which is exactly what makes a rename
    like this risky.
    """
    return _FILENAME
# Sentinel the macOS IDE addon sends when a project is open but no file is selected.
_ADDON_NO_FILE_SENTINEL = "(none)"


def _get_active_session_folder() -> Path | None:
    # Indirection so tests can monkeypatch.
    from daemon.misc.content_files import get_active_session_folder
    return get_active_session_folder()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
    """Render a canonical UTC timestamp for humans, in the machine's timezone.

    Output must stay within `[0-9A-Za-z: ]` — that is exactly the character
    class both participant.html parsing regexes expect after ` — `. Nothing
    here calls `locale.setlocale`, so `%b` is safely ASCII today, but if that
    ever changes, a locale whose month abbreviation contains e.g. `.` or a
    non-ASCII letter would silently break the regex match and drop the row
    from the rendered tree.
    """
    dt = _to_local(ts)
    if not with_date:
        return f"{dt:%H:%M}"
    # Built by hand rather than with %-d, which is not portable across libcs.
    return f"{dt:%b} {dt.day} {dt:%H:%M}"


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


def count_open_files(folder: Path | None) -> int:
    """Number of files recorded in the session's opened-files.md (0 if none/absent).

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


def _save_doc(folder: Path, doc: Doc) -> None:
    atomic_write(folder / _FILENAME, doc.render())


def _check_ref(owner: str, repo: str, ref: str, path: str) -> bool | None:
    """Probe whether `path` is present on `ref`.

    Returns True (present), False (definitely absent — either the ref exists
    but lacks the path, or the ref itself does not exist), or None when no
    probe reached a definitive answer: a network blip, a GitHub 5xx, or a
    rate limit on every call tried. A caller must never treat None as False —
    that is exactly the bug this tri-state return exists to prevent: a
    transient failure must not read as "the file/branch is not there".
    """
    tree = github_client.get_repo_tree(owner, repo, ref)
    if tree is None:
        # Confirmed 404/403 on the tree endpoint: this ref does not exist on
        # GitHub, so the path cannot be on it either — no need to also probe
        # the blob HEAD.
        return False
    if not isinstance(tree, github_client.RepoTree):
        # tree is UNKNOWN: the tree call itself was inconclusive. A direct
        # blob HEAD is a second, independent chance at a definitive answer.
        present = github_client.head_blob(owner, repo, ref, path)
        return present if isinstance(present, bool) else None
    if tree.truncated:
        present = github_client.head_blob(owner, repo, ref, path)
        return present if isinstance(present, bool) else None
    return path in tree.paths


def _ref_exists(owner: str, repo: str, ref: str) -> bool | None:
    """Whether `ref` itself exists on GitHub — used only to choose between the
    `no-branch` and `not-pushed` reasons once both refs are confirmed to lack
    the path. `get_repo_tree` is cached, so this piggybacks on the call
    `_check_ref` already made for the same (owner, repo, ref) and costs no
    extra request.
    """
    tree = github_client.get_repo_tree(owner, repo, ref)
    if tree is None:
        return False
    if isinstance(tree, github_client.RepoTree):
        return True
    return None


def resolve_entry(
    owner: str, repo: str, branch: str, default_branch: str, path: str
) -> tuple[str | None, str | None, str | None]:
    """Resolve one path to a blob URL. Returns (blob_url, ref, reason).

    Captured branch first, default branch second, no link third — see
    docs/superpowers/specs/2026-08-04-open-files-git-linking-design.md.

    `reason` is "unknown" whenever neither ref could be checked to a
    definitive answer — a transient GitHub failure must never be reported as
    "not-pushed" or "no-branch", both of which participants would read as
    settled facts about the code.
    """
    definitive = True
    if branch:
        present = _check_ref(owner, repo, branch, path)
        if present:
            return github_client.build_blob_url(owner, repo, branch, path), "branch", None
        if present is None:
            definitive = False
    if branch != default_branch:
        present = _check_ref(owner, repo, default_branch, path)
        if present:
            return github_client.build_blob_url(owner, repo, default_branch, path), "default", None
        if present is None:
            definitive = False

    if not definitive:
        return None, None, "unknown"

    branch_exists = _ref_exists(owner, repo, branch) if branch else True
    return None, None, ("not-pushed" if branch_exists else "no-branch")


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

    ts = _utcnow_iso()
    existing = next((e for e in repo_obj.entries if e.path == path), None)

    if rate_limited:
        if existing is not None:
            # A rate-limited retry cannot check anything, so it must not
            # clobber a link we already resolved — only recency moves.
            existing.branch, existing.ts = effective_branch, ts
            _save_doc(folder, doc)
            return
        blob_url, ref, reason = None, None, "rate-limited"
    else:
        blob_url, ref, reason = resolve_entry(owner, repo, effective_branch,
                                              default_branch, path)
        if reason == "unknown" and existing is not None:
            # Same principle as the rate-limited case: a transient GitHub
            # failure must not overwrite an entry we already resolved.
            existing.branch, existing.ts = effective_branch, ts
            _save_doc(folder, doc)
            return

    if existing is None:
        repo_obj.entries.append(Entry(path=path, branch=effective_branch, ts=ts,
                                      blob_url=blob_url, ref=ref, reason=reason))
    else:
        existing.branch, existing.ts = effective_branch, ts
        existing.blob_url, existing.ref, existing.reason = blob_url, ref, reason

    _save_doc(folder, doc)


def migrate_session_if_needed(folder: Path) -> None:
    """One-shot migration: convert session-state.json `git_repos` to opened-files.md
    and remove the key.

    No-op if opened-files.md already exists (so we never re-migrate or overwrite live state).
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
        branch = repo_entry.get("branch", "")
        if not isinstance(branch, str):
            branch = ""
        files = repo_entry.get("files", []) or []
        for f in files:
            if not isinstance(f, str):
                continue
            _record_into_folder(folder, url, branch, f)

    # Strip the key and re-save
    payload.pop("git_repos", None)
    js_path.write_text(_json.dumps(payload, indent=2), encoding="utf-8")
    _log.info(_NAME, f"migrated {len(repos)} repo(s) for session {folder.name}")
