"""macOS adapter — real implementations using osascript, plistlib, subprocess.

This module provides the real macOS-specific functionality:
- IntelliJ project tracking
- Local beep sound
- Google Drive process detection

For Docker/Linux testing, swap this with daemon.adapters.stub.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

from daemon import log


# ── IntelliJ ────────────────────────────────────────────────────────────────

def probe_intellij(timeout: float = 2.0) -> dict | None:
    """Return {project, path, branch, frontmost} for the active IntelliJ project."""
    from daemon.intellij.tracker import probe_intellij_state
    return probe_intellij_state(timeout)


# ── Beep ────────────────────────────────────────────────────────────────────

def beep() -> None:
    """Play a beep sound via osascript."""
    try:
        subprocess.run(
            ["osascript", "-e", "beep"],
            capture_output=True, text=True, timeout=2, check=False,
        )
    except Exception:
        pass


# ── Google Drive process detection ──────────────────────────────────────────

def is_google_drive_running() -> bool:
    """Check if the Google Drive desktop app is running."""
    if sys.platform != "darwin":
        return True
    try:
        proc = subprocess.run(
            ["pgrep", "-x", "Google Drive"],
            capture_output=True, text=True, check=False,
        )
        return proc.returncode == 0
    except Exception:
        return True
