"""
Configuration dataclass, environment loading, and session folder discovery.
"""

import os
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
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
DAEMON_POLL_INTERVAL = 1  # seconds
DAEMON_HOST_PORT = int(os.environ.get("DAEMON_HOST_PORT", "1234"))
# Open the host panel in the browser at startup. start.sh sets it to 0 on
# auto-update restarts so a push to master does not spawn a tab each time.
DAEMON_OPEN_BROWSER = os.environ.get("DAEMON_OPEN_BROWSER", "1").strip().lower() not in ("0", "false", "no", "")


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
    folder = Path(os.environ.get("TRANSCRIPTION_FOLDER", "/Users/victorrentea/workspace/victor-macos-addons/addons-output"))
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


# Session folder names start with a date prefix, then a space/underscore and the topic:
#   2026-09-15 Topic            one day
#   2026-09-14..15 Topic        consecutive days (bare end day, same month)
#   2026-08-31..1 Topic         consecutive days rolling into the next month
#   2026-09-4+9 Topic           two separate, non-consecutive days
#   2026-10-12+14..16 Topic     segments chain: Oct 12, then Oct 14 to 16
#   2026-08-31..09-01 Topic     end given as MM-DD
#   2026-12-31..2027-01-02 T    end given as a full date
# Days may be written with one or two digits.
_DATE_STEP = r"(\.\.|\+)(?:(\d{4})-(\d{2})-(\d{1,2})|(\d{2})-(\d{1,2})|(\d{1,2}))"
_SESSION_FOLDER_RE = re.compile(
    r"^[^0-9]*(\d{4})-(\d{2})-(\d{1,2})"
    r"((?:" + _DATE_STEP + r")*)"
    r"(?=[\s_]|$)"
)
_DATE_STEP_RE = re.compile(_DATE_STEP)


@dataclass(frozen=True)
class SessionFolderDates:
    """The day(s) a session folder name says the session runs on."""

    ranges: tuple[tuple[date, date], ...]  # each (first, last) day, inclusive, in order

    @property
    def start(self) -> date:
        return self.ranges[0][0]

    @property
    def end(self) -> date:
        return self.ranges[-1][1]

    def covers(self, day: date) -> bool:
        return any(first <= day <= last for first, last in self.ranges)

    def label(self) -> str:
        return " + ".join(
            first.isoformat() if first == last else f"{first.isoformat()} .. {last.isoformat()}"
            for first, last in self.ranges
        )


def _next_date(prev: date, ey, em, ed, em2, ed2, ed3) -> date:
    """Resolve one '..X' / '+X' step relative to the date before it."""
    if ey:
        return date(int(ey), int(em), int(ed))
    if em2:
        d = date(prev.year, int(em2), int(ed2))
        return d.replace(year=prev.year + 1) if d < prev else d
    day = int(ed3)
    if day > prev.day:
        return date(prev.year, prev.month, day)
    return (prev.replace(day=1) + timedelta(days=32)).replace(day=day)


def parse_session_folder_dates(name: str) -> Optional[SessionFolderDates]:
    """Parse the date prefix of a session folder name; None if it has none.

    Each '..X' extends the current range up to X; each '+X' starts a new one.
    A bare day at or before the previous day rolls into the next month
    ("2026-08-31..1" is Aug 31 to Sep 1); a MM-DD before the previous date
    rolls into the next year. Raises ValueError for a non-existent date or a
    date before the one preceding it.
    """
    m = _SESSION_FOLDER_RE.match(name)
    if not m:
        return None
    y, mo, d, steps = m.groups()[:4]
    prev = date(int(y), int(mo), int(d))
    ranges = [[prev, prev]]
    for sep, *parts in _DATE_STEP_RE.findall(steps):
        nxt = _next_date(prev, *parts)
        if nxt < prev:
            raise ValueError(f"{nxt} < {prev}")
        if sep == "..":
            ranges[-1][1] = nxt
        else:
            ranges.append([nxt, nxt])
        prev = nxt
    return SessionFolderDates(tuple((a, b) for a, b in ranges))

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
        try:
            dates = parse_session_folder_dates(entry.name)
        except ValueError as e:
            log.error("session", f"Invalid dates in folder name {entry.name!r}: {e}")
            continue
        if dates is not None and dates.covers(today):
            matches.append((dates.start, entry.name, entry))

    if not matches:
        return None, None

    # Latest start_date; tie-break: alphabetically last name
    matches.sort(key=lambda x: (x[0], x[1]))
    _, _, session_folder = matches[-1]

    if len(matches) > 1:
        log.info(
            "session",
            f"Multiple folders match today: {[m[1] for m in matches]}; selected: {session_folder.name}",
        )

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
