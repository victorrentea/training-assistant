"""Session state management: daemon state persistence, session helpers."""

import json
import os
import re
from datetime import date, datetime
from pathlib import Path

from daemon import log
from daemon.persisted_models import (
    PersistedGlobalState,
    PersistedSessionMeta,
    PersistedSessionState,
)

# Module-level ws_client reference, set by daemon/__main__.py at startup
_ws_client = None
_current_session_id: str | None = None


def set_ws_client(client) -> None:
    """Set the module-level ws_client reference."""
    global _ws_client
    _ws_client = client


def set_current_session_id(session_id: str | None) -> None:
    """Set the active server session_id for session-scoped HTTP calls."""
    global _current_session_id
    _current_session_id = session_id


def announce_session_id(session_id: str, session_type: str | None = None) -> None:
    """Immediately notify Railway of a new session_id via WS."""
    if _ws_client and _ws_client.connected:
        if session_type is None:
            from daemon.participant.state import participant_state
            session_type = participant_state.mode or "workshop"
        _ws_client.send({"type": "set_session_id", "session_id": session_id, "session_type": session_type})


def announce_session_cleared() -> None:
    """Notify Railway that no session is active."""
    if _ws_client and _ws_client.connected:
        _ws_client.send({"type": "set_session_id"})


def get_current_session_id() -> str | None:
    return _current_session_id

# ── Constants ──────────────────────────────────────────────────────────────────
GLOBAL_STATE_FILENAME = "global-state.json"
_LEGACY_GLOBAL_STATE_FILENAME = "training-assistant-global-state.json"
_LEGACY_DAEMON_STATE_FILENAME = "daemon_state.json"

_SLIDES_MANIFEST_CANDIDATES = (
    "slides_manifest.json",
    "slides-manifest.json",
    "slides.json",
    "pdf_manifest.json",
    "pdfs.json",
)
_SLIDES_MANIFEST_ERRORS: set[str] = set()

_DEFAULT_MATERIALS_FOLDER = Path("/Users/victorrentea/Documents/workshop-materials")


# ── Materials folder resolution ────────────────────────────────────────────────

def resolve_materials_folder() -> Path | None:
    """Resolve materials folder used by indexer and materials mirror."""
    env_value = os.environ.get("MATERIALS_FOLDER", "").strip()
    if env_value:
        folder = Path(env_value).expanduser()
        return folder if folder.exists() and folder.is_dir() else None

    candidates = [
        _DEFAULT_MATERIALS_FOLDER,
        Path(__file__).parent.parent / "materials",
        Path.home() / "workspace" / "training-assistant" / "materials",
    ]
    for candidate in candidates:
        folder = candidate.expanduser()
        if folder.exists() and folder.is_dir():
            return folder
    return None


# ── Daemon state persistence ────────────────────────────────────────────────────

SESSION_STATE_FILENAME = "session-state.json"
_LEGACY_SESSION_STATE_FILENAME = ".session-state.json"
SESSION_META_FILENAME = SESSION_STATE_FILENAME
_LEGACY_SESSION_META_FILENAME = "session_meta.json"
_SESSION_META_KEYS = ("session_id", "session_type")


def load_daemon_state(sessions_root: Path) -> dict:
    """Load daemon state. Returns raw JSON dict from disk (any format).
    New format: {active_session_id: str|None}.
    Old formats (main/talk, stack) are returned as-is for caller to handle."""
    state_file = sessions_root / GLOBAL_STATE_FILENAME
    if not state_file.exists():
        legacy_global = sessions_root / _LEGACY_GLOBAL_STATE_FILENAME
        if legacy_global.exists():
            try:
                legacy_global.replace(state_file)
            except Exception:
                state_file = legacy_global
        else:
            legacy_file = sessions_root / _LEGACY_DAEMON_STATE_FILENAME
            if legacy_file.exists():
                state_file = legacy_file
    if not state_file.exists():
        return {}
    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            log.error("session", f"Invalid {GLOBAL_STATE_FILENAME}: root must be object")
            return {}
        try:
            model = PersistedGlobalState.model_validate(raw)
            return model.model_dump(mode="json", exclude_unset=True)
        except Exception as e:
            # Keep backward compatibility with unknown legacy fields.
            log.error("session", f"Invalid {GLOBAL_STATE_FILENAME} payload; using raw data: {e}")
            return raw
    except Exception as e:
        log.error("session", f"Failed to load daemon state: {e}")
        return {}


def save_daemon_state(sessions_root: Path, daemon_state: dict) -> None:
    """Persist daemon state to disk atomically.
    New format: {active_session_id: str|None}."""
    try:
        sessions_root.mkdir(parents=True, exist_ok=True)
        payload = daemon_state if isinstance(daemon_state, dict) else {}
        payload = PersistedGlobalState.model_validate(payload).model_dump(mode="json", exclude_unset=True)
        path = sessions_root / GLOBAL_STATE_FILENAME
        existing: dict = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(existing, dict):
                    existing = {}
            except Exception:
                existing = {}
        changed_keys: list[str] = []
        for k in sorted(set(existing.keys()) | set(payload.keys())):
            if existing.get(k) != payload.get(k):
                changed_keys.append(k)
        if not changed_keys:
            return
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")
        tmp.replace(path)
        log.info("session", f"💾 {GLOBAL_STATE_FILENAME}: {', '.join(changed_keys)}")
    except Exception as e:
        log.error("session", f"Failed to save daemon state: {e}")


def load_session_meta(session_folder: Path) -> dict:
    """Load session metadata from session-state.json.
    Returns {session_id} or {} if missing."""
    data = load_session_state(session_folder)
    if not isinstance(data, dict):
        return {}
    try:
        model = PersistedSessionMeta.model_validate(data)
        validated = model.model_dump(mode="json", exclude_unset=True)
    except Exception:
        validated = data
    meta = {k: validated[k] for k in _SESSION_META_KEYS if k in validated}
    return meta if "session_id" in meta else {}


def save_session_meta(session_folder: Path, meta: dict) -> None:
    """Persist session metadata into session-state.json."""
    try:
        current = load_session_state(session_folder)
        merged = dict(current) if isinstance(current, dict) else {}
        validated_meta = meta if isinstance(meta, dict) else {}
        try:
            validated_meta = PersistedSessionMeta.model_validate(validated_meta).model_dump(
                mode="json",
                exclude_unset=True,
            )
        except Exception as e:
            log.error("session", f"Invalid session meta payload in {session_folder.name}: {e}")
        for key in _SESSION_META_KEYS:
            if key in validated_meta:
                merged[key] = validated_meta[key]
        save_session_state(session_folder, merged)
    except Exception as e:
        log.error("session", f"Failed to save session meta to {session_folder.name}: {e}")


def find_session_folder_by_id(sessions_root: Path, session_id: str) -> Path | None:
    """Scan session folders and return the one whose session_id matches.
    Checks metadata in session-state.json first (fast), then legacy snapshots."""
    if not sessions_root.exists() or not session_id:
        return None
    try:
        folders = sorted(
            (f for f in sessions_root.iterdir() if f.is_dir()),
            key=lambda p: p.name,
            reverse=True,
        )
    except Exception:
        return None
    for folder in folders:
        # Check metadata in session-state.json first (daemon-owned, always up to date)
        meta = load_session_meta(folder)
        if meta.get("session_id") == session_id:
            return folder
        # Fall back to session-state snapshots (server snapshot, may lag)
        for ss_path in (folder / SESSION_STATE_FILENAME, folder / _LEGACY_SESSION_STATE_FILENAME):
            if not ss_path.exists():
                continue
            try:
                data = json.loads(ss_path.read_text(encoding="utf-8"))
                if data.get("session_id") == session_id:
                    return folder
            except Exception:
                pass
    return None


# ── Session pause/resume helpers ───────────────────────────────────────────────

def pause_session(session: dict, now: datetime, reason: str = "explicit") -> None:
    """Add an open pause interval to a session (no-op if already paused)."""
    pauses = session.setdefault("paused_intervals", [])
    if not any(p.get("to") is None for p in pauses):
        pauses.append({"from": now.isoformat(), "to": None, "reason": reason})


def resume_session(session: dict, now: datetime) -> None:
    """Close the most recent open pause interval on a session."""
    for p in reversed(session.get("paused_intervals", [])):
        if p.get("to") is None:
            p["to"] = now.isoformat()
            return


# ── Session date helper ────────────────────────────────────────────────────────

def session_start_date(session_entry: dict) -> date | None:
    """Extract the session start date from a session stack entry."""
    try:
        return datetime.fromisoformat(session_entry["started_at"]).date()
    except Exception:
        return None


# ── Session state file I/O ─────────────────────────────────────────────────────

def session_state_path(session_folder: Path) -> Path:
    return session_folder / SESSION_STATE_FILENAME


def load_session_state(session_folder: Path) -> dict:
    """Load session-state.json and return a dict snapshot; returns {} on missing/invalid."""
    path = session_state_path(session_folder)
    if not path.exists():
        legacy_meta = session_folder / _LEGACY_SESSION_META_FILENAME
        if legacy_meta.exists():
            try:
                data = json.loads(legacy_meta.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    session_folder.mkdir(parents=True, exist_ok=True)
                    tmp = path.with_name(f"{SESSION_STATE_FILENAME}.tmp")
                    tmp.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")
                    tmp.replace(path)
                    legacy_meta.unlink(missing_ok=True)
                    log.info("session", "💾 migrated legacy session state")
                    return data
            except Exception:
                pass
        return {}
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        data = json.loads(raw)
        if isinstance(data, dict):
            try:
                model = PersistedSessionState.model_validate(data)
                return model.model_dump(mode="json", exclude_unset=True)
            except Exception as e:
                # Keep unknown legacy fields while still validating known structures where possible.
                log.error("session", f"Invalid {SESSION_STATE_FILENAME} payload; using raw data: {e}")
                return data
        log.error("session", f"Invalid {SESSION_STATE_FILENAME}: root must be object")
        return {}
    except Exception as e:
        log.error("session", f"Failed to load {SESSION_STATE_FILENAME}: {e}")
        return {}


# Participant-page view slugs (see _KNOWN_VIEWS in daemon/participant/router.py) → what
# the participant was actually doing there. "engagement" alone says nothing; "viewed slides"
# tells us how the tool is being used.
_VIEW_ACTIVITIES = {
    "activity": "the live activity",
    "slides": "slides",
    "summary": "the summary",
    "notes": "notes",
    "agenda": "the agenda",
    "report-bug": "the bug report form",
    "upload-paste": "the paste/upload form",
    "files": "files",
}


_MAX_SLIDE_REFS = 4


def _slide_ref(slug, page) -> str:
    """Render a slide as 'deck:page' (just 'deck' when the page is unknown)."""
    slug = str(slug or "").strip() or "unknown"
    return f"{slug}:{page}" if isinstance(page, int) else slug


def _current_slide_ref(snapshot: dict) -> str | None:
    """The slide the host is projecting right now, as 'deck:page' — participants follow it."""
    cur = snapshot.get("current_slide") if isinstance(snapshot, dict) else None
    if not isinstance(cur, dict) or not str(cur.get("slug") or "").strip():
        return None
    return _slide_ref(cur.get("slug"), cur.get("page"))


def _join_slide_refs(refs: list[str]) -> str:
    """Comma-join slide refs, capped so a bulk load does not print a wall of pages."""
    shown = sorted(set(refs))
    if len(shown) > _MAX_SLIDE_REFS:
        return f"{', '.join(shown[:_MAX_SLIDE_REFS])} +{len(shown) - _MAX_SLIDE_REFS} more"
    return ", ".join(shown)


def _describe_slides_viewed(old_v, new_v) -> str:
    """Name the (deck, page) pairs whose accumulated viewing time changed."""
    def as_map(v) -> dict:
        return {
            (sv.get("slug"), sv.get("page")): sv.get("seconds")
            for sv in (v if isinstance(v, list) else [])
            if isinstance(sv, dict)
        }

    old_m, new_m = as_map(old_v), as_map(new_v)
    changed = [k for k in set(old_m) | set(new_m) if old_m.get(k) != new_m.get(k)]
    refs = _join_slide_refs([_slide_ref(slug, page) for slug, page in changed])
    return f"({refs})" if refs else ""


def _describe_engagement(old_v, new_v, snapshot: dict) -> set[str]:
    """Translate a participant's changed engagement map into 'viewed <activity>' phrases.

    Participants have no per-person page of their own to report, but the slides view follows
    the host, so the currently projected slide is what they were looking at.
    """
    old_views = old_v if isinstance(old_v, dict) else {}
    new_views = new_v if isinstance(new_v, dict) else {}
    changed = [v for v in set(old_views) | set(new_views) if old_views.get(v) != new_views.get(v)]
    if not changed:
        return {"viewed unknown"}
    slide_ref = _current_slide_ref(snapshot)
    phrases = set()
    for view in changed:
        activity = _VIEW_ACTIVITIES.get(str(view), "unknown")
        if view == "slides" and slide_ref:
            activity = f"slides {slide_ref}"
        phrases.add(f"viewed {activity}")
    return phrases


def _describe_changed_value(key: str, old_v, new_v, snapshot: dict) -> str:
    """Return a parenthesised sub-field hint for a changed value, or '' if no detail to add.

    For dict[str, dict] values (e.g. participants, qa_questions) this reports added/removed
    entry counts and the union of changed inner field names — so a save log like
    'participants(score)' tells us a score changed, not just that the collection moved.

    Slide-shaped values are named as 'deck:page' instead of just reporting that they moved.
    """
    if key == "slides_viewed":
        return _describe_slides_viewed(old_v, new_v)
    if key == "current_slide":
        ref = _current_slide_ref({"current_slide": new_v})
        return f"({ref})" if ref else ""
    if not (isinstance(old_v, dict) and isinstance(new_v, dict)):
        return ""
    # Only drill in if entries look like nested dicts (e.g. participants[uuid] -> {name, score, ...}).
    has_dict_entries = any(isinstance(v, dict) for v in old_v.values()) or any(
        isinstance(v, dict) for v in new_v.values()
    )
    if not has_dict_entries:
        return ""
    added = set(new_v.keys()) - set(old_v.keys())
    removed = set(old_v.keys()) - set(new_v.keys())
    subfields: set[str] = set()
    for k in set(old_v.keys()) & set(new_v.keys()):
        ov, nv = old_v.get(k), new_v.get(k)
        if isinstance(ov, dict) and isinstance(nv, dict):
            for fk in set(ov.keys()) | set(nv.keys()):
                if ov.get(fk) != nv.get(fk):
                    if fk == "engagement":
                        subfields |= _describe_engagement(ov.get(fk), nv.get(fk), snapshot)
                    else:
                        subfields.add(fk)
        elif ov != nv:
            subfields.add("<value>")
    parts: list[str] = []
    if added:
        parts.append(f"+{len(added)}")
    if removed:
        parts.append(f"-{len(removed)}")
    parts.extend(sorted(subfields))
    return f"({', '.join(parts)})" if parts else ""


def save_session_state(session_folder: Path, snapshot: dict) -> None:
    """Atomically writes session-state.json to the session folder."""
    session_folder.mkdir(parents=True, exist_ok=True)
    payload = dict(snapshot) if isinstance(snapshot, dict) else {}
    # Preserve session metadata fields that may have been written separately.
    existing = load_session_state(session_folder)
    if isinstance(existing, dict):
        existing_session_id = existing.get("session_id")
        # Session ID is immutable per folder once assigned.
        if isinstance(existing_session_id, str) and existing_session_id.strip():
            payload["session_id"] = existing_session_id.strip()
        for key in _SESSION_META_KEYS:
            if key in existing and key not in payload:
                payload[key] = existing[key]
    payload = PersistedSessionState.model_validate(payload).model_dump(mode="json", exclude_unset=True)
    # Detect changed top-level keys for logging, with sub-field hints for dict-of-dict values.
    changed_descriptors: list[str] = []
    all_keys = set(existing.keys()) | set(payload.keys()) if isinstance(existing, dict) else set(payload.keys())
    for k in sorted(all_keys):
        old_v = existing.get(k) if isinstance(existing, dict) else None
        new_v = payload.get(k)
        if old_v != new_v:
            changed_descriptors.append(f"{k}{_describe_changed_value(k, old_v, new_v, payload)}")
    if not changed_descriptors:
        return
    path = session_state_path(session_folder)
    tmp = path.with_name(f"{SESSION_STATE_FILENAME}.tmp")
    tmp.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")
    tmp.replace(path)
    log.info("session", f"💾 {', '.join(changed_descriptors)}")


# ── Notes file helper ──────────────────────────────────────────────────────────

def find_notes_in_folder(folder: Path) -> Path | None:
    """Find the most recently modified .txt notes file in a session folder."""
    if not folder.exists():
        return None
    txt_files = sorted(
        [f for f in folder.iterdir() if f.suffix.lower() == ".txt"],
        key=lambda f: f.stat().st_mtime,
    )
    return txt_files[-1] if txt_files else None


def create_notes_file(folder: Path) -> Path:
    """Create a notes file named '<folder name> - notes.txt' and return it.

    The file's first line is its own filename, so the notes are self-labelling when
    opened or exported. Called at session start when no .txt notes file exists yet, so
    the trainer always has a notes file to write into. Never clobbers an existing file.
    """
    notes_file = folder / f"{folder.name} - notes.txt"
    if not notes_file.exists():
        notes_file.write_text(f"{notes_file.name}\n", encoding="utf-8")
    return notes_file


# ── Slides manifest helpers ────────────────────────────────────────────────────

def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "slide"


def _iso_from_value(value) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value)).isoformat()
        except Exception:
            return None
    return None


def _normalize_slides_manifest(raw) -> list[dict]:
    if raw is None:
        return []

    entries = raw.get("slides") if isinstance(raw, dict) and "slides" in raw else raw
    normalized: list[dict] = []

    if isinstance(entries, dict):
        iterable = []
        for slug, value in entries.items():
            if isinstance(value, str):
                iterable.append({"slug": str(slug), "name": str(slug), "url": value})
            elif isinstance(value, dict):
                iterable.append({"slug": str(slug), **value})
    elif isinstance(entries, list):
        iterable = entries
    else:
        return []

    seen: set[str] = set()
    for idx, item in enumerate(iterable):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("title") or item.get("slug") or f"Slide {idx + 1}").strip()
        url = str(
            item.get("url")
            or item.get("pdf_url")
            or item.get("published_url")
            or item.get("obfuscated_url")
            or ""
        ).strip()
        if not name or not url:
            continue
        slug = str(item.get("slug") or _slugify(name)).strip() or _slugify(name)
        if slug in seen:
            slug = f"{slug}-{idx+1}"
        seen.add(slug)
        normalized.append({
            "name": name,
            "slug": slug,
            "url": url,
            "updated_at": _iso_from_value(
                item.get("updated_at")
                or item.get("uploaded_at")
                or item.get("modified_at")
                or item.get("timestamp")
            ),
            "etag": item.get("etag"),
            "last_modified": item.get("last_modified") or item.get("lastModified"),
        })
    return normalized


def load_slides_manifest(session_folder: Path | None) -> list[dict]:
    if not session_folder:
        return []
    for filename in _SLIDES_MANIFEST_CANDIDATES:
        path = session_folder / filename
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            slides = _normalize_slides_manifest(raw)
            if slides:
                _SLIDES_MANIFEST_ERRORS.discard(str(path))
                return slides
        except Exception as e:
            key = str(path)
            if key not in _SLIDES_MANIFEST_ERRORS:
                log.error("session", f"Failed reading {filename}: {e}")
                _SLIDES_MANIFEST_ERRORS.add(key)
    return []
