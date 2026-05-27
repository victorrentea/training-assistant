"""Minimal GitHub HTTP client used by files_md for default-branch + blob verification.

Process-lifetime in-memory cache. Unauthenticated requests (60/hr per IP) are
plenty for typical workshop traffic; we degrade gracefully on rate limits.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Final

import certifi

from daemon import log as _log

_NAME = "github"
_TIMEOUT_S = 3.0
_USER_AGENT = "TrainingAssistant/1.0"


@dataclass(frozen=True)
class RepoInfo:
    default_branch: str


class _Sentinel:
    pass


RATE_LIMITED: Final = _Sentinel()

# Cache: key=(owner, repo). Values:
#   RepoInfo  → public, default_branch known.
#   None      → known private/404 (negative cache, never re-queried).
#   missing key → unknown.
# RATE_LIMITED responses are NOT cached (so we retry on next event).
_REPO_CACHE: dict[tuple[str, str], RepoInfo | None] = {}


def reset_cache() -> None:
    _REPO_CACHE.clear()


def _ssl_ctx():
    return ssl.create_default_context(cafile=certifi.where())


def _is_rate_limited(err: urllib.error.HTTPError) -> bool:
    if err.code != 403:
        return False
    remaining = err.headers.get("X-RateLimit-Remaining") if err.headers else None
    return remaining == "0"


def get_repo_info(owner: str, repo: str) -> RepoInfo | None | _Sentinel:
    """Look up the repo. Returns:
       - RepoInfo on success (public)
       - None for private/missing (negative-cached)
       - RATE_LIMITED on rate-limit (not cached; caller may degrade gracefully)
    """
    key = (owner, repo)
    if key in _REPO_CACHE:
        return _REPO_CACHE[key]

    url = f"https://api.github.com/repos/{owner}/{repo}"
    req = urllib.request.Request(
        url, method="GET",
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S, context=_ssl_ctx()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        branch = str(data.get("default_branch") or "").strip() or "main"
        info = RepoInfo(default_branch=branch)
        _REPO_CACHE[key] = info
        return info
    except urllib.error.HTTPError as err:
        if _is_rate_limited(err):
            _log.error(_NAME, f"rate-limited on /repos/{owner}/{repo}")
            return RATE_LIMITED
        if err.code in (404, 403):
            _REPO_CACHE[key] = None
            return None
        _log.error(_NAME, f"repo lookup {owner}/{repo} failed: {err}")
        _REPO_CACHE[key] = None
        return None
    except Exception as exc:  # noqa: BLE001
        _log.error(_NAME, f"repo lookup {owner}/{repo} crashed: {exc}")
        _REPO_CACHE[key] = None
        return None


def head_blob(owner: str, repo: str, branch: str, path: str) -> bool:
    """HEAD the GitHub blob page. Returns True iff 200."""
    url = f"https://github.com/{owner}/{repo}/blob/{branch}/{path}"
    req = urllib.request.Request(
        url, method="HEAD",
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S, context=_ssl_ctx()) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as err:
        return 200 <= err.code < 300
    except Exception:  # noqa: BLE001
        return False


def build_blob_url(owner: str, repo: str, branch: str, path: str) -> str:
    return f"https://github.com/{owner}/{repo}/blob/{branch}/{path}"
