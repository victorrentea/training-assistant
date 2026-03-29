"""Stub adapter — no-op implementations for Docker/Linux/CI environments.

All macOS-specific operations return safe defaults. No subprocess calls,
no osascript, no plist files. Used when DAEMON_ADAPTER=stub.
"""

from daemon import log


def probe_powerpoint(timeout_seconds: float = 5.0) -> tuple[dict | None, str | None]:
    """Always returns no PowerPoint running."""
    return None, None


def read_audiohijack_language() -> str | None:
    """Always returns None (no Audio Hijack)."""
    return None


def set_audiohijack_language(lang_code: str) -> None:
    """No-op."""
    log.info("stub", f"set_audiohijack_language({lang_code}) — stubbed")


def restart_audiohijack() -> None:
    """No-op."""
    log.info("stub", "restart_audiohijack() — stubbed")


def probe_intellij(timeout: float = 2.0) -> dict | None:
    """Always returns None (no IntelliJ)."""
    return None


def beep() -> None:
    """No-op."""
    pass


def is_google_drive_running() -> bool:
    """Always returns True (assume available)."""
    return True
