"""macOS adapter — real implementations using osascript, plistlib, subprocess.

This module provides the real macOS-specific functionality:
- PowerPoint probe (slide number, presentation name, frontmost)
- Audio Hijack control (read language, set language, restart)
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


# ── PowerPoint ──────────────────────────────────────────────────────────────

_PPT_NO_APP = "__NO_PPT__"
_PPT_NO_PRESENTATION = "__NO_PRESENTATION__"
_PPT_SLIDE_UNKNOWN = "__SLIDE_UNKNOWN__"

_PPT_APPLESCRIPT = """
if application "Microsoft PowerPoint" is not running then
    return "__NO_PPT__"
end if

tell application "Microsoft PowerPoint"
    if (count of presentations) is 0 then
        return "__NO_PRESENTATION__"
    end if

    set presentationName to name of active presentation
    set slideNumber to 1
    set isPresenting to "false"

    try
        if (count of slide show windows) > 0 then
            set isPresenting to "true"
            set slideNumber to current show position of slide show view of slide show window 1
        else
            try
                set slideNumber to slide index of slide of view of active window
            on error
                try
                    set slideNumber to slide index of slide of view of document window 1
                on error
                    set slideNumber to "__SLIDE_UNKNOWN__"
                end try
            end try
        end if
    on error
        set slideNumber to "__SLIDE_UNKNOWN__"
    end try

    set isFrontmost to "false"
    tell application "System Events"
        try
            set isFrontmost to (frontmost of application process "Microsoft PowerPoint") as string
        end try
    end tell

    return presentationName & tab & isPresenting & tab & (slideNumber as string) & tab & isFrontmost
end tell
""".strip()


def _coerce_slide_number(value) -> int:
    raw = str(value or "").strip()
    if not raw or raw.lower() == "missing value" or raw == _PPT_SLIDE_UNKNOWN:
        return 1
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1


def _parse_powerpoint_probe_output(raw: str) -> dict | None:
    text = (raw or "").strip()
    if not text or text in {_PPT_NO_APP, _PPT_NO_PRESENTATION}:
        return None
    parts = text.split("\t")
    if len(parts) < 2:
        return None
    presentation = parts[0].strip()
    if not presentation:
        return None
    if len(parts) >= 3:
        is_presenting = parts[1].strip() == "true"
        slide_number = _coerce_slide_number(parts[2].strip())
    else:
        is_presenting = False
        slide_number = _coerce_slide_number(parts[1].strip())
    is_frontmost = parts[3].strip() == "true" if len(parts) >= 4 else True
    return {
        "presentation": presentation,
        "slide": slide_number,
        "presenting": is_presenting,
        "frontmost": is_frontmost,
    }


def probe_powerpoint(timeout_seconds: float = 5.0) -> tuple[dict | None, str | None]:
    """Probe PowerPoint via osascript. Returns (state_dict, error_string)."""
    try:
        result = subprocess.run(
            ["osascript", "-e", _PPT_APPLESCRIPT],
            capture_output=True,
            text=True,
            timeout=max(0.1, timeout_seconds),
            check=False,
        )
    except FileNotFoundError:
        return None, "osascript not available on PATH"
    except subprocess.TimeoutExpired:
        return None, f"osascript timed out after {timeout_seconds:.1f}s"
    except Exception as e:
        return None, f"osascript failed: {e}"

    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        if not details:
            details = f"osascript exit code {result.returncode}"
        return None, details

    return _parse_powerpoint_probe_output(result.stdout), None


# ── Audio Hijack ────────────────────────────────────────────────────────────

_AUDIOHIJACK_SESSIONS_PLIST = os.path.expanduser(
    "~/Library/Application Support/Audio Hijack 4/Sessions.plist"
)


def read_audiohijack_language() -> str | None:
    """Read the current TranscribeBlock languageCode from Sessions.plist."""
    import plistlib
    try:
        with open(_AUDIOHIJACK_SESSIONS_PLIST, "rb") as f:
            data = plistlib.load(f)
        for session_item in data.get("modelItems", []):
            for block in session_item.get("sessionData", {}).get("geBlocks", []):
                if block.get("geObjectInfo") == "TranscribeBlock":
                    lang = block.get("geNodeProperties", {}).get("languageCode")
                    if lang:
                        return lang
    except Exception:
        pass
    return None


def set_audiohijack_language(lang_code: str) -> None:
    """Kill AudioHijack, update TranscribeBlock languageCode, restart."""
    import plistlib
    import time as _time  # used for the post-kill settle sleep below

    subprocess.run(["pkill", "-x", "Audio Hijack"], capture_output=True)
    _time.sleep(1.5)

    with open(_AUDIOHIJACK_SESSIONS_PLIST, "rb") as f:
        data = plistlib.load(f)
    changed = False
    for session_item in data.get("modelItems", []):
        for block in session_item.get("sessionData", {}).get("geBlocks", []):
            if block.get("geObjectInfo") == "TranscribeBlock":
                block.setdefault("geNodeProperties", {})["languageCode"] = lang_code
                changed = True
    if changed:
        with open(_AUDIOHIJACK_SESSIONS_PLIST, "wb") as f:
            plistlib.dump(data, f)

    _start_audiohijack_with_retry()


def restart_audiohijack() -> None:
    """Restart Audio Hijack process."""
    subprocess.run(["pkill", "-x", "Audio Hijack"], capture_output=True)
    _start_audiohijack_with_retry()


def _start_audiohijack_with_retry(retries: int = 5, backoff: float = 3.0) -> None:
    """Launch Audio Hijack, retrying up to `retries` times with `backoff` seconds between attempts."""
    import time as _time

    for attempt in range(1, retries + 1):
        result = subprocess.run(["open", "-a", "Audio Hijack"], capture_output=True)
        if result.returncode == 0:
            return
        if attempt < retries:
            _time.sleep(backoff)
    # Last attempt already tried; log failure silently (caller decides whether to raise)


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
