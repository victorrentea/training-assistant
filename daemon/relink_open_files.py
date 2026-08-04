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
    """Re-resolve one session folder. Returns a counts summary.

    Only writes the file back when the rendered text actually changed —
    `_save_doc` goes through `os.replace`, which bumps the file's mtime even
    when the bytes are identical, and the daemon's file-watcher treats any
    mtime change as "files changed" and broadcasts a Files-tab update to every
    connected participant. In the steady state (nothing moved, nothing
    degraded) that broadcast would fire on every single summary generation
    for no reason. The raw text is read before `_load_doc` runs so that a
    load-time normalisation of a legacy document — which SHOULD be persisted
    — still counts as a change.
    """
    target = folder / files_md.session_filename()
    summary = {"repos": 0, "entries": 0, "linked_branch": 0,
               "linked_default": 0, "unlinked": 0, "skipped": 0}
    if not target.exists():
        return summary
    try:
        before = target.read_text(encoding="utf-8")
    except OSError as exc:
        # Unreadable is indistinguishable from absent for this pass: the
        # summarizer that invokes this CLI can simply re-run it later.
        _log.error(_NAME, f"read {target} failed: {exc}")
        return summary

    doc = files_md._load_doc(folder)
    for repo_obj in doc.repos:
        # _owner_repo's invariant is that its input already went through
        # _canonical_repo_url — true for a URL just written by this module,
        # but repo_obj.url here was parsed back out of markdown, so it must
        # be re-canonicalized rather than assumed clean.
        canonical = files_md._canonical_repo_url(repo_obj.url)
        if canonical is None:
            _log.info(_NAME, f"skipping {repo_obj.url} (not a canonical github.com URL)")
            summary["skipped"] += len(repo_obj.entries)
            continue
        owner, repo = files_md._owner_repo(canonical)
        info = github_client.get_repo_info(owner, repo)
        if not isinstance(info, github_client.RepoInfo):
            # None (private/404) or RATE_LIMITED. Leave the block untouched: a
            # 404 or a rate limit here says more about the network than about
            # the repo.
            _log.info(_NAME, f"skipping {repo_obj.url} (unavailable)")
            summary["skipped"] += len(repo_obj.entries)
            continue
        summary["repos"] += 1
        repo_obj.default_branch = info.default_branch
        for entry in repo_obj.entries:
            blob_url, ref, reason = files_md.resolve_entry(
                owner, repo, entry.branch, info.default_branch, entry.path)
            if reason == "unknown":
                # A transient GitHub failure on this one entry must not
                # overwrite whatever it already had — leave it exactly as is.
                summary["skipped"] += 1
                continue
            entry.blob_url, entry.ref, entry.reason = blob_url, ref, reason
            summary["entries"] += 1
            if ref == "branch":
                summary["linked_branch"] += 1
            elif ref == "default":
                summary["linked_default"] += 1
            else:
                summary["unlinked"] += 1

    rendered = doc.render()
    if rendered != before:
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
