"""macOS adapter — real implementations using osascript, plistlib, subprocess.

This module provides the real macOS-specific functionality:
- Local beep sound
- Google Drive process detection

For Docker/Linux testing, swap this with daemon.adapters.stub.
"""

import subprocess
import sys

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


# ── Open file in editor ───────────────────────────────────────────────────────

def open_in_vscode(path) -> None:
    """Open a file in Visual Studio Code. Best-effort; never raises."""
    try:
        subprocess.run(
            ["open", "-a", "Visual Studio Code", str(path)],
            capture_output=True, text=True, timeout=5, check=False,
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
