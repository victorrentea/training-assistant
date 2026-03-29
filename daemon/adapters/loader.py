"""Adapter loader — selects macos or stub adapter based on DAEMON_ADAPTER env var.

Usage:
    from daemon.adapters.loader import adapter
    state, err = adapter.probe_powerpoint()
"""

import os
import sys
from types import ModuleType

_ADAPTER_ENV = "DAEMON_ADAPTER"


def _load_adapter() -> ModuleType:
    choice = os.environ.get(_ADAPTER_ENV, "").strip().lower()

    if choice == "stub":
        from daemon.adapters import stub
        return stub

    if choice == "macos":
        from daemon.adapters import macos
        return macos

    # Auto-detect: use macos on darwin, stub everywhere else
    if sys.platform == "darwin":
        from daemon.adapters import macos
        return macos
    else:
        from daemon.adapters import stub
        return stub


adapter = _load_adapter()
