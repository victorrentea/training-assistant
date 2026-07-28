"""Minimal GitHub HTTP client used by files_md for default-branch + blob verification.

Process-lifetime in-memory cache. Unauthenticated requests (60/hr per IP) are
plenty for typical workshop traffic; we degrade gracefully on rate limits.
"""
from __future__ import annotations

import json
import os
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

# Override targets for hermetic tests. The user-facing blob URL written to
# opened-files.md (see build_blob_url) is always real github.com — only the internal
# verification calls follow these env vars.
_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com").rstrip("/")
_VERIFY_BLOB_BASE = os.environ.get("GITHUB_BLOB_BASE", "https://github.com").rstrip("/")


@dataclass(frozen=True)
class RepoInfo:
    default_branch: str


@dataclass(frozen=True)
class RepoTree:
    paths: frozenset[str]                   # full paths in the tree (blobs only)
    paths_by_basename: dict[str, list[str]] # basename → [full paths]
    truncated: bool


class _Sentinel:
    pass


RATE_LIMITED: Final = _Sentinel()

# Cache: key=(owner, repo). Values:
#   RepoInfo  → public, default_branch known.
#   None      → known private/404 (negative cache, never re-queried).
#   missing key → unknown.
# RATE_LIMITED responses are NOT cached (so we retry on next event).
_REPO_CACHE: dict[tuple[str, str], RepoInfo | None] = {}

# Cache: key=(owner, repo, branch). Values:
#   RepoTree  → successfully fetched tree.
#   None      → 404/403 or persistent failure (negative cache).
#   missing key → not yet fetched.
# Rate-limited responses are NOT cached (retry on next call).
_TREE_CACHE: dict[tuple[str, str, str], RepoTree | None] = {}


def reset_cache() -> None:
    _REPO_CACHE.clear()
    _TREE_CACHE.clear()


_SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def _is_rate_limited(err: urllib.error.HTTPError) -> bool:
    if err.code != 403:
        return False
    remaining = err.headers.get("X-RateLimit-Remaining") if err.headers else None
    return remaining == "0"


def get_repo_info(owner: str, repo: str) -> RepoInfo | None | _Sentinel:
    """Look up the repo. Returns:
       - RepoInfo on success (public, cached)
       - None for private/missing (cached deterministically)
       - RATE_LIMITED on rate-limit (NOT cached)
       - None on transient network errors / other HTTP codes (NOT cached)
    """
    key = (owner, repo)
    if key in _REPO_CACHE:
        return _REPO_CACHE[key]

    url = f"{_API_BASE}/repos/{owner}/{repo}"
    req = urllib.request.Request(
        url, method="GET",
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S, context=_SSL_CTX) as resp:
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
        # Other HTTP errors (5xx etc.) — transient, do not cache
        _log.error(_NAME, f"repo lookup {owner}/{repo} HTTP {err.code}")
        return None
    except Exception as exc:  # noqa: BLE001
        # Network errors (DNS, SSL, timeout) — transient, do not cache
        _log.error(_NAME, f"repo lookup {owner}/{repo} crashed: {exc}")
        return None


def get_repo_tree(owner: str, repo: str, branch: str) -> RepoTree | None:
    """Fetch and cache the repo tree. Returns None on network/HTTP error.

    Negative results (404, 403, persistent failures) are cached as None.
    Rate-limited responses are NOT cached (retry on next call).
    """
    key = (owner, repo, branch)
    if key in _TREE_CACHE:
        return _TREE_CACHE[key]

    url = f"{_API_BASE}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    req = urllib.request.Request(
        url, method="GET",
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S, context=_SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # Only "blob" entries are files (skip "tree" entries = dirs).
        paths: list[str] = []
        for entry in data.get("tree", []):
            if entry.get("type") == "blob":
                p = entry.get("path")
                if isinstance(p, str) and p:
                    paths.append(p)
        truncated = bool(data.get("truncated", False))
        index: dict[str, list[str]] = {}
        for p in paths:
            b = p.rsplit("/", 1)[-1]
            index.setdefault(b, []).append(p)
        tree = RepoTree(paths=frozenset(paths), paths_by_basename=index, truncated=truncated)
        _TREE_CACHE[key] = tree
        return tree
    except urllib.error.HTTPError as err:
        if _is_rate_limited(err):
            _log.error(_NAME, f"rate-limited on /trees/{owner}/{repo}/{branch}")
            return None  # do NOT cache
        if err.code in (404, 403):
            _TREE_CACHE[key] = None
            return None
        _log.error(_NAME, f"tree fetch {owner}/{repo}/{branch} HTTP {err.code}")
        return None
    except Exception as exc:  # noqa: BLE001
        _log.error(_NAME, f"tree fetch {owner}/{repo}/{branch} crashed: {exc}")
        return None


def head_blob(owner: str, repo: str, branch: str, path: str) -> bool:
    """HEAD the GitHub blob page. Returns True iff 200."""
    url = f"{_VERIFY_BLOB_BASE}/{owner}/{repo}/blob/{branch}/{path}"
    req = urllib.request.Request(
        url, method="HEAD",
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S, context=_SSL_CTX) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as err:
        return 200 <= err.code < 300
    except Exception:  # noqa: BLE001
        return False


def build_blob_url(owner: str, repo: str, branch: str, path: str) -> str:
    return f"https://github.com/{owner}/{repo}/blob/{branch}/{path}"
