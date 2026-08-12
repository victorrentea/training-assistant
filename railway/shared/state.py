from datetime import datetime
from typing import Optional

from fastapi import WebSocket


class AppState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.participants: dict[str, WebSocket] = {}
        # uuids that joined THIS session (online or offline) — the gateway's notion
        # of "is this one of ours". Display names/avatars belong to the daemon.
        self.participant_history: set[str] = set()
        self.participant_avatars: dict[str, str] = {}
        self.participant_ips: dict[str, str] = {}  # uuid → IP address
        self.uploaded_files: dict[str, list[dict]] = {}  # uuid → [{id, filename, size, disk_path}]
        self.upload_next_id: int = 0
        self.slides: list[dict] = []
        self.daemon_last_seen: Optional[datetime] = None
        self.daemon_ws: Optional[WebSocket] = None
        self.claude_inbox_ws: WebSocket | None = None
        self.daemon_code_timestamp: Optional[str] = None  # ISO timestamp of last git commit in daemon repo
        self.slides_updated: dict[str, dict] = {}      # slug -> {status, size_bytes, downloaded_at}
        self.session_type: str = "workshop"     # "workshop" | "talk"
        self.mode: str = "workshop"  # "workshop" | "talk"
        self.session_id: str | None = None  # set only by daemon via set_session_id WS push
        # Clean up uploaded files from disk
        import shutil
        from pathlib import Path
        upload_dir = Path(".server-data") / "uploads"
        if upload_dir.exists():
            shutil.rmtree(upload_dir, ignore_errors=True)

    def touch_daemon(self):
        """Update daemon last-seen timestamp."""
        from datetime import datetime, timezone
        self.daemon_last_seen = datetime.now(timezone.utc)


state = AppState()
