"""Whether the print after a save may wait: a save Victor Mac made, with PowerPoint in front.

Every save of a deck open in PowerPoint makes local_publish.py print the changed slides
there, and PowerPoint shows that print as a progress bar. After Victor's own ⌘S he wants it
at once; after a save he did not make (Victor Mac's AutoSave, every 3 min of unsaved edits,
or its slides-seen save) it waits until PowerPoint is in the background (Victor, 2026-11-20).

Victor Mac notes each scripted save in `~/.victor-addons/powerpoint-scripted-saves.json`:
`{path: {"started": epoch, "mtime": epoch}}`, `mtime` being the file's right after the save
and missing while the save is under way (`ScriptedSaveLog` in victor-mac).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTED_SAVES = Path.home() / ".victor-addons" / "powerpoint-scripted-saves.json"
_POWERPOINT_BUNDLE = "com.microsoft.Powerpoint"
# A save under way that never wrote its end (Victor Mac killed mid-save) stops counting after this.
_SAVE_UNDER_WAY_S = 120.0


def _real(path: str | Path) -> str:
    return os.path.realpath(os.path.expanduser(str(path)))


def is_scripted_save(path: Path, mtime: float, log_file: Path | None = None) -> bool:
    """True when the save that gave `path` this mtime was made by Victor Mac, not by hand."""
    try:
        saves = json.loads((log_file or SCRIPTED_SAVES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    target = _real(path)
    for logged, entry in saves.items():
        if _real(logged) != target or not isinstance(entry, dict):
            continue
        started = float(entry.get("started") or 0)
        after = entry.get("mtime")
        if after is None:
            return started - 1 <= mtime <= started + _SAVE_UNDER_WAY_S
        return abs(float(after) - mtime) < 1.0
    return False


def powerpoint_frontmost() -> bool:
    """PowerPoint is the app in front. `lsappinfo` needs no Automation grant, unlike
    System Events. Anything unexpected reads as "not in front": the print then runs."""
    if sys.platform != "darwin":
        return False
    try:
        front = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True, timeout=5).stdout.strip()
        if not front:
            return False
        info = subprocess.run(["lsappinfo", "info", "-only", "bundleid", front],
                              capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return f'"{_POWERPOINT_BUNDLE}"'.lower() in info.lower()


def defer_print(path: Path, mtime: float) -> bool:
    """The print after this save waits for PowerPoint to leave the front."""
    return is_scripted_save(path, mtime) and powerpoint_frontmost()
