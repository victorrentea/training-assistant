"""OpenAPI contract metadata enrichment for generated docs.

Adds contract-focused extensions on operations:
- x-feature: canonical feature ID for API.md grouping
- x-doc-notes: important operational notes (when applicable)
"""

from __future__ import annotations

from typing import Any

HTTP_METHODS = {"get", "post", "put", "delete", "patch"}


def _feature_for_misc_path(path: str) -> str:
    if "paste" in path or "upload" in path:
        return "paste_upload"
    if "feedback" in path:
        return "feedback"
    if "/notes" in path or "/summary" in path:
        return "notes_summary"
    if "slides-cache-status" in path:
        return "slides"
    if "transcription-language" in path:
        return "transcription"
    return "misc"


def _feature_from_tag_and_path(tag: str, path: str) -> str:
    if tag in ("", "_untagged", "session"):
        return "session_management"
    if tag in ("participant", "host-state"):
        return "identity"
    if tag == "leaderboard":
        return "scores_leaderboard"
    if tag == "misc":
        return _feature_for_misc_path(path)
    return tag


# Keep this small and focused on operationally important behavior.
_DOC_NOTES: dict[tuple[str, str], list[str]] = {
    ("POST", "/api/participant/poll/vote"): [
        "Votes are final once submitted; re-vote is rejected.",
    ],
    ("GET", "/api/participant/state"): [
        "Returns participant-personalized full state snapshot.",
    ],
    ("GET", "/api/{session_id}/host/state"): [
        "Returns host-facing full state snapshot.",
    ],
    ("GET", "/api/transcription-language/request"): [
        "Consumes and clears the pending transcription language request.",
    ],
    ("POST", "/api/transcription-language"): [
        "Accepted values: ro, en, auto.",
    ],
    ("GET", "/api/participant/slides-cache-status"): [
        "Primarily for diagnostics; UI cache invalidation is event-driven via slides_cache_status WS.",
    ],
}


def enrich_openapi_contract(schema: dict[str, Any]) -> None:
    """Mutate OpenAPI schema in place with x-feature and x-doc-notes metadata."""
    for path, methods in schema.get("paths", {}).items():
        if not isinstance(path, str) or not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue

            tags = operation.get("tags") or ["_untagged"]
            tag = str(tags[0]) if tags else "_untagged"
            operation["x-feature"] = _feature_from_tag_and_path(tag, path)

            key = (method.upper(), path)
            if key in _DOC_NOTES:
                existing = operation.get("x-doc-notes") or []
                if not isinstance(existing, list):
                    existing = [str(existing)]
                merged: list[str] = [str(n).strip() for n in existing if str(n).strip()]
                for note in _DOC_NOTES[key]:
                    if note not in merged:
                        merged.append(note)
                if merged:
                    operation["x-doc-notes"] = merged
