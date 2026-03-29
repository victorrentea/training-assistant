"""Session state management: daemon state persistence, key-points I/O, session helpers."""

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from daemon import log
from daemon.http import _get_json, _post_json

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


def get_current_session_id() -> str | None:
    return _current_session_id

# ── Constants ──────────────────────────────────────────────────────────────────
_KEY_POINTS_FILE = "transcript_discussion.md"
_KEY_POINTS_FILE_LEGACY_MD = "transcript_keypoints.md"
_KEY_POINTS_FILE_LEGACY = "key_points.json"
_DAEMON_STATE_FILENAME = "daemon_state.json"

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


# ── Daily timing check ─────────────────────────────────────────────────────────

def check_daily_timing(now_time=None):
    """Returns 'midnight', 'auto_pause', 'warning', or None based on current time."""
    from datetime import time as _time
    if now_time is None:
        now_time = datetime.now().time()
    # Check midnight first (spans 23:59-00:01)
    if now_time >= _time(23, 59) or now_time < _time(0, 1):
        return "midnight"
    # auto_pause uses threshold (>= 18:00), deduplication prevents re-firing
    if now_time >= _time(18, 0):
        return "auto_pause"
    if now_time >= _time(17, 30):
        return "warning"
    return None


# ── Key points I/O ─────────────────────────────────────────────────────────────

def load_key_points(session_folder: Path) -> tuple[list[dict], int]:
    """Load key points from session folder. Returns (points, watermark).
    Reads transcript_discussion.md (new) or falls back to transcript_keypoints.md (legacy md)
    or key_points.json (oldest legacy)."""
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
            log.info("session", f"Loaded {len(points)} key points{label} from {session_folder.name}")
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
            log.info("session", f"Loaded {len(points)} key points (legacy) from {session_folder.name}")
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

def load_daemon_state(sessions_root: Path) -> dict:
    """Load daemon state. Returns {main: dict|None, talk: dict|None}.
    Migrates old {stack:[...]} format transparently."""
    state_file = sessions_root / _DAEMON_STATE_FILENAME
    empty = {"main": None, "talk": None}
    if not state_file.exists():
        return empty
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as e:
        log.error("session", f"Failed to load daemon state: {e}")
        return empty
    # Migration: old format had {stack: [...]}
    if "stack" in data and "main" not in data:
        stack = data["stack"]
        active = [s for s in stack if not s.get("ended_at")]
        return {
            "main": {**active[0], "status": "active"} if len(active) >= 1 else None,
            "talk": {**active[1], "status": "active"} if len(active) >= 2 else None,
        }
    return data


def daemon_state_to_stack(daemon_state: dict) -> list[dict]:
    """Convert {main, talk} daemon state dict to the in-memory session stack list.
    Sessions with status 'ended' are excluded — they are not restored."""
    main = daemon_state.get("main")
    talk = daemon_state.get("talk")
    # If main session is ended, treat as no session at all
    if main and main.get("status") == "ended":
        return []
    stack = []
    if main:
        stack.append(main)
    # If talk session is ended, keep main but discard talk
    if talk and talk.get("status") != "ended":
        stack.append(talk)
    return stack


def stack_to_daemon_state(stack: list[dict]) -> dict:
    """Convert in-memory session stack list to {main, talk} dict for persistence."""
    def _with_status(s: dict) -> dict:
        paused = any(p.get("to") is None for p in s.get("paused_intervals", []))
        return {**s, "status": "paused" if paused else "active"}
    return {
        "main": _with_status(stack[0]) if len(stack) >= 1 else None,
        "talk": _with_status(stack[1]) if len(stack) >= 2 else None,
    }


def save_daemon_state(sessions_root: Path, daemon_state: dict) -> None:
    """Persist {main, talk} daemon state to disk atomically."""
    try:
        sessions_root.mkdir(parents=True, exist_ok=True)
        path = sessions_root / _DAEMON_STATE_FILENAME
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(daemon_state, default=str, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        log.error("session", f"Failed to save daemon state: {e}")


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

def save_session_state(session_folder: Path, snapshot: dict) -> None:
    """Atomically writes session_state.json to the session folder."""
    path = session_folder / "session_state.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot, default=str, indent=2))
    tmp.replace(path)


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


# ── Server sync helper ─────────────────────────────────────────────────────────

def sync_session_to_server(
    config, stack: list[dict], key_points: list[dict],
    session_state: dict | None = None,
    **extra_fields,
) -> None:
    """Push session stack and key points to server via WS (falls back to HTTP).
    If session_state is provided, it is included for a plain restore (no participant disconnect).
    Extra keyword arguments (e.g. action, discussion_points) are merged into the payload."""
    daemon_state = stack_to_daemon_state(stack)
    payload: dict = {"main": daemon_state["main"], "talk": daemon_state["talk"], "key_points": key_points}
    if session_state is not None:
        payload["session_state"] = session_state
        if session_state.get("session_id"):
            payload["session_id"] = session_state["session_id"]
    payload.update(extra_fields)

    if _ws_client and _ws_client.connected:
        _ws_client.send({"type": "session_sync", **payload})
    else:
        sid = _current_session_id
        path = f"/api/{sid}/session/sync" if sid else "/api/session/sync"
        _post_json(
            f"{config.server_url}{path}",
            payload,
            config.host_username, config.host_password,
        )


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
