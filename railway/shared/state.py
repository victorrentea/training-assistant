import random
from datetime import datetime
from enum import Enum
from typing import Optional

from fastapi import WebSocket


class ActivityType(str, Enum):
    NONE = "none"
    POLL = "poll"
    WORDCLOUD = "wordcloud"
    QA = "qa"
    DEBATE = "debate"
    CODEREVIEW = "codereview"

class AppState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.participants: dict[str, WebSocket] = {}
        self.participant_history: set[str] = set()  # uuids seen in this session (online or offline)
        self.participant_names: dict[str, str] = {}  # uuid -> display_name
        self.participant_avatars: dict[str, str] = {}
        self.participant_ips: dict[str, str] = {}  # uuid → IP address
        self.paste_texts: dict[str, list[dict]] = {}  # uuid → [{id: int, text: str}, ...]
        self.paste_next_id: int = 0
        self.uploaded_files: dict[str, list[dict]] = {}  # uuid → [{id, filename, size, disk_path}]
        self.upload_next_id: int = 0
        self.locations: dict[str, str] = {}
        self.slides: list[dict] = []
        self.daemon_last_seen: Optional[datetime] = None
        self.daemon_ws: Optional[WebSocket] = None
        self.claude_inbox_ws: WebSocket | None = None
        self.daemon_code_timestamp: Optional[str] = None  # ISO timestamp of last git commit in daemon repo
        self.slides_current: Optional[dict] = None
        # Slides cache (server-side GDrive download)
        self.slides_updated: dict[str, dict] = {}      # slug -> {status, size_bytes, downloaded_at}
        self.notes_content: Optional[str] = None
        self.transcript_line_count: int = 0
        self.transcript_total_lines: int = 0
        self.transcript_latest_ts: Optional[str] = None
        self.transcript_last_content_at: Optional[datetime] = None
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
        self.session_type: str = "workshop"     # "workshop" | "talk"
        self.token_usage: dict = {"input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0}
        self.mode: str = "workshop"  # "workshop" | "talk"
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
