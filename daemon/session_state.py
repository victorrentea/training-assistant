"""Session state management: daemon state persistence, key-points I/O, session helpers."""

import json
import os
import re
from datetime import date, datetime, timedelta
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


def announce_session_id(session_id: str, session_type: str = "workshop") -> None:
    """Immediately notify Railway of a new session_id via WS."""
    if _ws_client and _ws_client.connected:
        _ws_client.send({"type": "set_session_id", "session_id": session_id, "session_type": session_type})


def announce_session_cleared() -> None:
    """Notify Railway that no session is active."""
    if _ws_client and _ws_client.connected:
        _ws_client.send({"type": "set_session_id"})


def get_current_session_id() -> str | None:
    return _current_session_id

# ── Constants ──────────────────────────────────────────────────────────────────
_KEY_POINTS_FILE = "transcript_discussion.md"
_KEY_POINTS_FILE_LEGACY_MD = "transcript_keypoints.md"
_KEY_POINTS_FILE_LEGACY = "key_points.json"
_AI_SUMMARY_FILE = "ai-summary.md"
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

_DOW_RE = re.compile(r"^([A-Z][a-z]{2})\s+(\d{2}:\d{2})\s+(.+)$")
_FRONTMATTER_WATERMARK_RE = re.compile(r"^watermark:\s*(\d+)")


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


# ── Key points I/O ─────────────────────────────────────────────────────────────

def load_key_points(session_folder: Path) -> tuple[list[dict], int]:
    """Load key points from session folder. Returns (points, watermark).
    Prefers ai-summary.md (external AI-generated file) if present.
    Falls back to transcript_discussion.md, transcript_keypoints.md (legacy md),
    or key_points.json (oldest legacy)."""
    # Prefer external ai-summary.md if present
    ai_summary_file = session_folder / _AI_SUMMARY_FILE
    if ai_summary_file.exists():
        try:
            text = ai_summary_file.read_text(encoding="utf-8", errors="replace").strip()
            points = []
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("- ") or line.startswith("* "):
                    text_content = line[2:].strip()
                elif line and line[0].isdigit() and ". " in line:
                    text_content = line.split(". ", 1)[1].strip()
                else:
                    text_content = line
                if text_content:
                    points.append({"text": text_content, "source": "notes"})
            log.info("session", f"Summary found ({len(points)} lines): {_AI_SUMMARY_FILE}")
            return points, 0
        except Exception as e:
            log.error("session", f"Failed to load {_AI_SUMMARY_FILE}: {e}")

    md_file = session_folder / _KEY_POINTS_FILE
    legacy_md_file = session_folder / _KEY_POINTS_FILE_LEGACY_MD
    json_file = session_folder / _KEY_POINTS_FILE_LEGACY

    def _parse_md_file(path: Path, label: str) -> tuple[list[dict], int]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            watermark = 0
            points = []
            in_frontmatter = False
            seen_open = False
            for line in lines:
                stripped = line.strip()
                if not seen_open and stripped == "---":
                    in_frontmatter = True
                    seen_open = True
                    continue
                if in_frontmatter:
                    if stripped == "---":
                        in_frontmatter = False
                        continue
                    m = _FRONTMATTER_WATERMARK_RE.match(stripped)
                    if m:
                        watermark = int(m.group(1))
                    continue
                if not stripped:
                    continue
                m = _DOW_RE.match(stripped)
                if m:
                    points.append({"text": m.group(3), "time": m.group(2), "source": "discussion"})
                else:
                    points.append({"text": stripped, "source": "discussion"})
            log.info("session", f"Summary ({len(points)} points{label})")
            return points, watermark
        except Exception as e:
            log.error("session", f"Failed to load key points: {e}")
            return [], 0

    if md_file.exists():
        return _parse_md_file(md_file, "")

    if legacy_md_file.exists():
        return _parse_md_file(legacy_md_file, " (legacy md)")

    if json_file.exists():
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            points = data.get("points", data.get("locked", []) + data.get("draft", []))
            watermark = data.get("watermark", 0)
            log.info("session", f"Summary ({len(points)} points, legacy)")
            return points, watermark
        except Exception as e:
            log.error("session", f"Failed to load key points: {e}")
            return [], 0

    return [], 0


def save_key_points(
    session_folder: Path,
    points: list[dict],
    watermark: int = 0,
    session_date: date | None = None,
) -> None:
    """Save key points to transcript_discussion.md with DOW HH:MM prefix per line."""
    try:
        session_folder.mkdir(parents=True, exist_ok=True)

        # Only timed discussion points go to disk; notes-only bullets are ephemeral
        timed = [(p, p["time"]) for p in points if p.get("time")]

        # Sort by time and detect midnight crossings for DOW assignment
        def _mins(t: str) -> int:
            try:
                return int(t[:2]) * 60 + int(t[3:5])
            except Exception:
                return 0

        timed.sort(key=lambda x: _mins(x[1]))

        base_date = session_date or date.today()
        current_date = base_date
        prev_mins: int | None = None
        lines = ["---", f"watermark: {watermark}", "---", ""]

        for point, time_str in timed:
            mins = _mins(time_str)
            # Crossed midnight: new time is significantly smaller than previous
            if prev_mins is not None and mins < prev_mins - 30:
                current_date += timedelta(days=1)
            prev_mins = mins
            dow = current_date.strftime("%a")
            lines.append(f"{dow} {time_str} {point['text']}")

        (session_folder / _KEY_POINTS_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        log.error("session", f"Failed to save key points: {e}")


# ── Daemon state persistence ────────────────────────────────────────────────────

SESSION_STATE_FILENAME = "session-state.json"
_LEGACY_SESSION_STATE_FILENAME = ".session-state.json"
SESSION_META_FILENAME = SESSION_STATE_FILENAME
_LEGACY_SESSION_META_FILENAME = "session_meta.json"
_SESSION_META_KEYS = ("session_id",)


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
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")
        tmp.replace(path)
        log.info("session", f"💾 {GLOBAL_STATE_FILENAME}")
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
                    log.info("session", f"💾 {SESSION_STATE_FILENAME} in {session_folder.name}")
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
    path = session_state_path(session_folder)
    tmp = path.with_name(f"{SESSION_STATE_FILENAME}.tmp")
    tmp.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")
    tmp.replace(path)
    log.info("session", f"💾 {SESSION_STATE_FILENAME} in {session_folder.name}")


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
