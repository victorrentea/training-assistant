import threading
import uuid


class MiscState:
    def __init__(self):
        self._lock = threading.Lock()
        self.paste_texts: dict[str, list[dict]] = {}  # uuid → [{id, text}]
        # TODO: notes_content, summary_points, summary_raw_markdown, summary_updated_at
        #  are currently synced from Railway state (via sync_from_restore).
        #  They should be read from disk files (ai-summary.md, notes.md) instead of stored in state.
        #  Deferred until summary/notes pipeline is refactored to write to known disk paths.
        self.notes_content: str | None = None
        self.summary_points: list[dict] = []
        self.summary_raw_markdown: str | None = None
        self.summary_updated_at: str | None = None  # ISO string
        self.slides_cache_status: dict[str, dict] = {}
        self.slides_catalog: dict[str, dict] = {}   # slug → catalog entry (drive_export_url, title, etc.)
        # Synced from Railway state (slides + session info)
        self.slides_current: dict | None = None
        self.session_main: dict | None = None
        self.session_name: str | None = None

    def sync_from_restore(self, data: dict):
        with self._lock:
            if "paste_texts" in data:
                self.paste_texts.clear()
                self.paste_texts.update(data["paste_texts"])
            if "notes_content" in data:
                self.notes_content = data["notes_content"]
            if "summary_points" in data:
                self.summary_points = list(data["summary_points"])
            if "summary_raw_markdown" in data:
                self.summary_raw_markdown = data["summary_raw_markdown"]
            if "summary_updated_at" in data:
                self.summary_updated_at = data["summary_updated_at"]
            if "slides_cache_status" in data:
                self.slides_cache_status.clear()
                self.slides_cache_status.update(data["slides_cache_status"])
            if "slides_current" in data:
                self.slides_current = data["slides_current"]
            if "session_main" in data:
                self.session_main = data["session_main"]
            if "session_name" in data:
                self.session_name = data["session_name"]

    def add_paste(self, pid: str, text: str) -> dict | None:
        entries = self.paste_texts.setdefault(pid, [])
        if len(entries) >= 10:
            return None
        entry = {"id": str(uuid.uuid4()), "text": text}
        entries.append(entry)
        return entry

    def dismiss_paste(self, target_uuid: str, paste_id: str) -> bool:
        if target_uuid not in self.paste_texts:
            return False
        self.paste_texts[target_uuid] = [
            e for e in self.paste_texts[target_uuid] if e["id"] != paste_id
        ]
        if not self.paste_texts[target_uuid]:
            del self.paste_texts[target_uuid]
        return True

    def update_slides_catalog(self, entries: list[dict]) -> None:
        """Replace the slides catalog with a new list of entries (keyed by slug)."""
        with self._lock:
            self.slides_catalog.clear()
            for entry in entries:
                slug = entry.get("slug")
                if slug:
                    self.slides_catalog[slug] = entry

    def snapshot(self) -> dict:
        return {
            "paste_texts": {k: list(v) for k, v in self.paste_texts.items()},
        }


misc_state = MiscState()
