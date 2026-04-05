import re
from pathlib import Path

_VERSION_JS = Path(__file__).parent.parent.parent / "static" / "version.js"
_VERSION_PATTERN = re.compile(r"APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]")

_cached_version: str = ""
_cached_mtime_ns: int | None = None


def get_backend_version() -> str:
    """Return backend deploy version from static/version.js (cached by file mtime)."""
    global _cached_version, _cached_mtime_ns
    try:
        stat = _VERSION_JS.stat()
    except OSError:
        return _cached_version

    if _cached_mtime_ns == stat.st_mtime_ns:
        return _cached_version

    try:
        raw = _VERSION_JS.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return _cached_version

    m = _VERSION_PATTERN.search(raw)
    _cached_version = m.group(1).strip() if m else ""
    _cached_mtime_ns = stat.st_mtime_ns
    return _cached_version
