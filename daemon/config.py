"""
Configuration dataclass, environment loading, and session folder discovery.
"""

import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from daemon import log

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SERVER_URL = "http://localhost:8000"
DEFAULT_MODEL      = "claude-sonnet-4-6"
DEFAULT_MINUTES    = 60
DEFAULT_TRANSCRIPT_MINUTES = 30  # default lookback window for transcript stats & summaries
MAX_CHARS_TO_CLAUDE = 60_000
DAEMON_POLL_INTERVAL = 3  # seconds


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class Config:
    folder: Path
    minutes: int
    server_url: str
    api_key: str
    model: str
    dry_run: bool
    host_username: str
    host_password: str
    topic: Optional[str] = None
    session_folder: Optional[Path] = None
    session_notes: Optional[Path] = None
    project_folder: Optional[str] = None


def load_secrets_env() -> None:
    """Load key=value pairs from the shared secrets file into os.environ."""
    default_path = Path.home() / ".training-assistants-secrets.env"
    secrets_file = Path(
        os.environ.get("TRAINING_ASSISTANTS_SECRETS_FILE", str(default_path))
    ).expanduser()
    if not secrets_file.exists():
        return
    for line in secrets_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def config_from_env(minutes: int = DEFAULT_MINUTES) -> "Config":
    """Build a Config from environment variables (after loading shared secrets)."""
    load_secrets_env()
    folder = Path(os.environ.get("TRANSCRIPTION_FOLDER", "/Users/victorrentea/Documents/transcriptions"))
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.error("daemon", "ANTHROPIC_API_KEY is not set")
        sys.exit(1)
    if not folder.exists() or not folder.is_dir():
        log.error("transcript", f"Folder not found: {folder}")
        sys.exit(1)
    project_folder = os.environ.get("PROJECT_FOLDER")
    return Config(
        folder=folder,
        minutes=minutes,
        server_url=os.environ.get("WORKSHOP_SERVER_URL", DEFAULT_SERVER_URL).rstrip("/"),
        api_key=api_key,
        model=os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL),
        dry_run=False,
        host_username=os.environ.get("HOST_USERNAME", "host"),
        host_password=os.environ.get("HOST_PASSWORD", ""),
        project_folder=project_folder,
    )


_SESSION_FOLDER_RE = re.compile(
    r"^[^0-9]*(\d{4}-\d{2}-\d{2})(?:\.\.(\d{2}(?:-\d{2})?))?[\s_]"
)

MAX_SESSION_NOTES_CHARS = 20_000


def find_session_folder(today: date) -> tuple[Optional[Path], Optional[Path]]:
    """Returns (session_folder, session_notes). Both None if not found."""
    sessions_root_str = os.environ.get(
        "SESSIONS_FOLDER",
        str(Path.home() / "My Drive" / "Cursuri" / "###sesiuni"),
    )
    sessions_root = Path(sessions_root_str).expanduser()
    if not sessions_root.exists() or not sessions_root.is_dir():
        log.error("session", f"SESSIONS_FOLDER not found: {sessions_root}")
        return None, None

    matches: list[tuple[date, str, Path]] = []
    for entry in sessions_root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.endswith(' talk'):
            continue
        m = _SESSION_FOLDER_RE.match(entry.name)
        if not m:
            continue
        try:
            start = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        g2 = m.group(2)
        try:
            if g2 is None:
                end = start
            elif "-" in g2:
                mm, dd = g2.split("-")
                end = date(start.year, int(mm), int(dd))
            else:
                end = date(start.year, start.month, int(g2))
        except ValueError:
            log.error("session", f"Invalid end date in: {entry.name}")
            continue
        if end < start:
            log.error("session", f"End < start in: {entry.name}")
            continue
        if start <= today <= end:
            matches.append((start, entry.name, entry))

    if not matches:
        return None, None

    if len(matches) > 1:
        log.error("session", f"Multiple folders match today: {[m[1] for m in matches]}")

    # Latest start_date; tie-break: alphabetically last name
    matches.sort(key=lambda x: (x[0], x[1]))
    _, _, session_folder = matches[-1]

    # Find most recently modified .txt file
    txt_files = sorted(
        [f for f in session_folder.iterdir() if f.suffix.lower() == ".txt"],
        key=lambda f: f.stat().st_mtime,
    )
    session_notes = txt_files[-1] if txt_files else None

    return session_folder, session_notes


def read_session_notes(config: "Config") -> str:
    """Read session notes file from config.session_notes. Returns '' on missing/failure."""
    if not config.session_notes:
        return ""
    try:
        raw = config.session_notes.read_text(encoding="utf-8", errors="replace")
        if len(raw) > MAX_SESSION_NOTES_CHARS:
            log.error("session", f"Notes truncated to {MAX_SESSION_NOTES_CHARS:,} chars")
            raw = raw[-MAX_SESSION_NOTES_CHARS:]
        return raw.strip()
    except OSError as exc:
        log.error("session", f"Could not read notes: {exc}")
        return ""
