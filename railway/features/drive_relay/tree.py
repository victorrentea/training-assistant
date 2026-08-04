"""Flatten a Drive folder into an ordered list of archive entries.

Separated from streaming so the whole transfer can be inspected before a single
byte moves: that is what lets the size cap and the error messages fire *before*
the download starts rather than halfway through it.
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass

from railway.features.drive_relay import drive_client, exclusions
from railway.features.drive_relay.drive_client import DriveFile

MAX_DEPTH = 20

# Drive names may contain anything, including "/" and "\". Archive paths must not:
# each archive_path is built by joining per-folder names with "/", so a raw "/"
# in a Drive name must never survive into a name segment.
_PATH_SEPARATORS = re.compile(r"[/\\]")
# After separators are flattened to ".", a name that used to be "../../etc" would
# otherwise leave literal ".." runs in the result. Collapse any run of 2+ dots
# down to one so no ".." substring can ever appear in an archive path.
_DOT_RUN = re.compile(r"\.{2,}")


@dataclass(frozen=True)
class PlannedEntry:
    archive_path: str
    file: DriveFile


@dataclass(frozen=True)
class TransferPlan:
    root_name: str
    entries: tuple[PlannedEntry, ...]
    known_bytes: int
    has_unsized_files: bool


def _safe_name(name: str) -> str:
    """Flatten a Drive-supplied name into a single safe archive path segment."""
    flattened = _PATH_SEPARATORS.sub(".", name)
    flattened = _DOT_RUN.sub(".", flattened)
    return flattened.strip() or "untitled"


def _unique(name: str, taken: set[str]) -> str:
    """Disambiguate 'Notes.pdf' → 'Notes (2).pdf' within a single folder."""
    if name not in taken:
        taken.add(name)
        return name
    stem, dot, extension = name.rpartition(".")
    if not dot:
        stem, extension = name, ""
    suffix = 2
    while True:
        candidate = f"{stem} ({suffix}){'.' + extension if extension else ''}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
        suffix += 1


def _resolve(file: DriveFile) -> DriveFile:
    """Follow a shortcut to the file it points at; other files pass through."""
    if not drive_client.is_shortcut(file) or not file.shortcut_target_id:
        return file
    return drive_client.get_metadata(file.shortcut_target_id)


def build_plan(root: DriveFile) -> TransferPlan:
    """Walk ``root`` and return every file that belongs in the archive.

    Guards against Drive's shortcut-induced cycles (a folder reachable from
    inside itself) and against pathological depth.
    """
    # A root passed in can itself be a shortcut — shortcuts have their own
    # shareable link, so a participant pasting one is normal, not exotic.
    # Resolve it once, up front, before deciding which branch applies: an
    # unresolved shortcut-to-folder would fail is_folder() and fall through
    # to the single-file branch below, wrapping the folder itself as a bogus
    # file entry instead of descending into it.
    resolved_root = _resolve(root)

    if not drive_client.is_folder(resolved_root):
        name = _safe_name(drive_client.archive_name(resolved_root))
        return TransferPlan(
            root_name=resolved_root.name,
            entries=(PlannedEntry(archive_path=name, file=resolved_root),),
            known_bytes=resolved_root.size or 0,
            has_unsized_files=resolved_root.size is None,
        )

    entries: list[PlannedEntry] = []
    known_bytes = 0
    has_unsized = False

    # Seed the cycle guard with the resolved folder's own id, not the
    # shortcut's — the guard must protect the folder actually being walked.
    visited: set[str] = {resolved_root.id}
    queue: deque[tuple[DriveFile, str, int]] = deque([(resolved_root, "", 0)])

    while queue:
        current, prefix, depth = queue.popleft()
        if depth >= MAX_DEPTH:
            continue
        taken: set[str] = set()
        pending_folders: list[tuple[DriveFile, str, int]] = []

        for child in drive_client.list_children(current.id):
            resolved = _resolve(child)
            if drive_client.is_folder(resolved):
                if resolved.id in visited or exclusions.is_excluded_dir(resolved.name):
                    continue
                visited.add(resolved.id)
                name = _unique(_safe_name(resolved.name), taken)
                pending_folders.append((resolved, f"{prefix}{name}/", depth + 1))
                continue

            if exclusions.is_excluded_file(resolved.name):
                continue

            name = _unique(_safe_name(drive_client.archive_name(resolved)), taken)
            entries.append(PlannedEntry(archive_path=f"{prefix}{name}", file=resolved))
            if resolved.size is None:
                has_unsized = True
            else:
                known_bytes += resolved.size

        queue.extend(pending_folders)

    return TransferPlan(
        root_name=resolved_root.name,
        entries=tuple(entries),
        known_bytes=known_bytes,
        has_unsized_files=has_unsized,
    )
