"""What never reaches a participant's download.

Session folders are mirrored to Drive as they are on disk, so they carry files
that exist for the tooling rather than for the audience — most importantly
attendees.md, which is the participant roster.

This deliberately duplicates most of daemon/materials/zip_builder.py instead of
importing it. The two answer different questions ("what goes into the archive I
build from the local folder" vs "what goes into the archive I relay from
Drive"), and they have already diverged: zip_builder skips *.zip so its own
archive will not swallow a previous one, while here wiki.zip is content the
participant actually wants.
"""
from __future__ import annotations

import fnmatch

# "Icon\r" is the real name of the macOS custom-folder-icon file; Finder and ls
# both render it as "Icon".
_EXCLUDED_NAMES = frozenset({"session-state.json", "attendees.md", "Icon", "Icon\r"})
_EXCLUDED_GLOBS = ("~$*",)
_EXCLUDED_DIRS = frozenset({".obsidian"})


def is_excluded_file(name: str) -> bool:
    """True when a file with this name must be kept out of the archive."""
    if name in _EXCLUDED_NAMES:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in _EXCLUDED_GLOBS)


def is_excluded_dir(name: str) -> bool:
    """True when a directory with this name must not be descended into."""
    return name in _EXCLUDED_DIRS
