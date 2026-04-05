from typing import Optional
from datetime import datetime
from fastapi import WebSocket
from enum import Enum
import asyncio
import random


class ActivityType(str, Enum):
    NONE = "none"
    POLL = "poll"
    WORDCLOUD = "wordcloud"
    QA = "qa"
    DEBATE = "debate"
    CODEREVIEW = "codereview"

LOTR_NAMES = [
    # Ordered by cultural popularity: most recognizable → least
    "Gandalf", "Frodo", "Aragorn", "Legolas", "Gollum",
    "Samwise", "Gimli", "Smaug", "Bilbo", "Saruman",
    "Galadriel", "Boromir", "Arwen", "Eowyn", "Merry",
    "Pippin", "Elrond", "Thorin", "Theoden", "Faramir",
    "Treebeard", "Shadowfax", "Radagast", "Tom Bombadil", "Eomer",
    "Haldir", "Glorfindel", "Celeborn", "Grima Wormtongue", "The One Ring"
]


class AppState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.participants: dict[str, WebSocket] = {}
        self.participant_history: set[str] = set()  # uuids seen in this session (online or offline)
        self.participant_names: dict[str, str] = {}  # uuid -> display_name
        self.participant_avatars: dict[str, str] = {}
        self.participant_universes: dict[str, str] = {}  # uuid → universe string
        self.participant_ips: dict[str, str] = {}  # uuid → IP address
        self.paste_texts: dict[str, list[dict]] = {}  # uuid → [{id: int, text: str}, ...]
        self.paste_next_id: int = 0
        self.uploaded_files: dict[str, list[dict]] = {}  # uuid → [{id, filename, size, disk_path}]
        self.upload_next_id: int = 0
        self.locations: dict[str, str] = {}
        self.quiz_request: Optional[dict] = None
        self.quiz_refine_request: Optional[dict] = None
        self.quiz_status: Optional[dict] = None
        self.slides: list[dict] = []
        self.daemon_last_seen: Optional[datetime] = None
        self.daemon_ws: Optional[WebSocket] = None
        self.daemon_code_timestamp: Optional[str] = None  # ISO timestamp of last git commit in daemon repo
        self.slides_current: Optional[dict] = None
        # Slides cache (server-side GDrive download)
        # Note: slides_catalog is NOT reset here — daemon may not re-send on soft reset
        if not hasattr(self, 'slides_catalog'):
            self.slides_catalog = {}
        self.slides_cache_status: dict[str, dict] = {}      # slug -> {status, size_bytes, downloaded_at, title}
        self.slides_download_events: dict[str, asyncio.Event] = {}  # slug -> event for waiters
        self.slides_gdrive_locks: dict[str, asyncio.Lock] = {}      # slug -> per-slug GDrive lock
        self.slides_fingerprints: dict[str, str] = {}        # slug -> last known fingerprint
        self.slides_download_semaphore: asyncio.Semaphore = asyncio.Semaphore(3)
        self.notes_content: Optional[str] = None
        self.transcript_line_count: int = 0
        self.transcript_total_lines: int = 0
        self.transcript_latest_ts: Optional[str] = None
        self.transcript_last_content_at: Optional[datetime] = None
        self.quiz_preview: Optional[dict] = None
        self.scores: dict[str, int] = {}
        self.base_scores: dict[str, int] = {}
        self.current_activity: ActivityType = ActivityType.NONE
        self.wordcloud_words: dict[str, int] = {}
        self.wordcloud_word_order: list[str] = []  # newest first
        self.wordcloud_topic: str = ""
        self.qa_questions: dict[str, dict] = {}
        # Each value: { id, text, author, upvoters: set[str], answered: bool, timestamp: float }
        self.summary_points: list[dict] = []
        self.summary_raw_markdown: str | None = None
        self.summary_updated_at: Optional[datetime] = None
        # Session state
        self.session_type: str = "workshop"     # "workshop" | "conference"
        self.session_name: str | None = None    # display name for current session
        self.token_usage: dict = {"input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}
        self.mode: str = "workshop"  # "workshop" | "conference"
        self.pending_deploy: dict | None = None  # {sha, message} set by watcher when push detected
        self.session_id: str | None = None  # 6-char alphanumeric session code for participant URLs
        self.slides_log, self.git_repos = [], []
        # Clean up uploaded files from disk
        import shutil
        from pathlib import Path
        upload_dir = Path(".server-data") / "uploads"
        if upload_dir.exists():
            shutil.rmtree(upload_dir, ignore_errors=True)

    def generate_session_id(self) -> str:
        """Generate a new 6-char alphanumeric session ID."""
        self.session_id = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=6))
        return self.session_id

    def touch_daemon(self):
        """Update daemon last-seen timestamp."""
        from datetime import datetime, timezone
        self.daemon_last_seen = datetime.now(timezone.utc)


state = AppState()


def get_avatar_filename(name: str) -> str:
    """Convert a LOTR name to its avatar filename slug."""
    return name.lower().replace(' ', '-') + '.png'


def assign_avatar(app_state: AppState, uuid: str, name: str) -> str:
    """Assign avatar based on name. LOTR names get their matching avatar on first
    assignment. Custom names get a unique avatar based on UUID hash.
    Never overwrites an existing avatar (preserves refresh_avatar choices)."""
    # If already assigned (initial or refreshed), keep it
    if uuid in app_state.participant_avatars:
        return app_state.participant_avatars[uuid]
    # LOTR name → match character avatar on first assignment
    if name in LOTR_NAMES:
        avatar = get_avatar_filename(name)
        app_state.participant_avatars[uuid] = avatar
        return avatar
    taken = set(app_state.participant_avatars.values())
    # Hash the name, not UUID, so same custom name → same avatar across tabs
    name_hash = sum(ord(c) for c in name) * 2654435761  # simple but deterministic
    preferred_index = name_hash % len(LOTR_NAMES)
    for offset in range(len(LOTR_NAMES)):
        avatar = get_avatar_filename(LOTR_NAMES[(preferred_index + offset) % len(LOTR_NAMES)])
        if avatar not in taken:
            app_state.participant_avatars[uuid] = avatar
            return avatar
    # All 30 taken — fall back to preferred
    avatar = get_avatar_filename(LOTR_NAMES[preferred_index])
    app_state.participant_avatars[uuid] = avatar
    return avatar


def refresh_avatar(app_state: AppState, uuid: str, rejected: set[str] | None = None) -> str | None:
    """Reassign a random avatar different from current and any previously rejected,
    ensuring uniqueness among connected participants."""
    current = app_state.participant_avatars.get(uuid)
    rejected = rejected or set()
    if current:
        rejected.add(current)

    # Get avatars used by ALL OTHER participants (connected or disconnected)
    taken_by_others = {avatar for uid, avatar in app_state.participant_avatars.items()
                       if uid != uuid and not uid.startswith("__")}

    all_avatars = [get_avatar_filename(n) for n in LOTR_NAMES]

    # Best case: not taken by others AND not previously rejected
    available = [a for a in all_avatars if a not in taken_by_others and a not in rejected]
    if not available:
        # Fallback: allow previously rejected but still avoid other participants' avatars
        available = [a for a in all_avatars if a not in taken_by_others and a != current]
    if not available:
        # Last resort: anything different from current
        available = [a for a in all_avatars if a != current]
    if not available:
        return None
    new_avatar = random.choice(available)
    app_state.participant_avatars[uuid] = new_avatar
    return new_avatar
