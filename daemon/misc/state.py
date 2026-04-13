import threading
import uuid
from pathlib import Path


class MiscState:
    def __init__(self):
        self._lock = threading.Lock()
        self.paste_texts: dict[str, list[dict]] = {}  # uuid → [{id, text}]
        self.uploaded_files: dict[str, list[dict]] = {}  # uuid -> [{id, filename, size, disk_path, seen_by_host}]
        # TODO: notes_content, summary_points, summary_raw_markdown, summary_updated_at
        #  are currently synced from Railway state (via sync_from_restore).
        #  They should be read from disk files (ai-summary.md, *.txt) instead of stored in state.
        #  Deferred until summary/notes pipeline is refactored to write to known disk paths.
        self.notes_content: str | None = None
        self.summary_points: list[dict] = []
        self.summary_raw_markdown: str | None = None
        self.summary_updated_at: str | None = None  # ISO string
        self.slides_cache_status: dict[str, dict] = {}
        self.slides_catalog: dict[str, dict] = {}   # slug → catalog entry (drive_export_url, title, etc.)
        # Synced from Railway state (slides + session info)
        self.slides_current: dict | None = None
        self.slides_viewed: list[dict] = []  # [{file_name, page, seconds}]
        self.gdrive_url: str | None = None
        self.agenda_docx_path: Path | None = None
        self.talk_presentation_name: str | None = None
        self.talk_presentation_url: str | None = None
        self.talk_presentation_slug: str | None = None

    def sync_from_restore(self, data: dict):
        with self._lock:
            if "paste_texts" in data:
                self.paste_texts.clear()
                self.paste_texts.update(data["paste_texts"])
            if "uploaded_files" in data:
                self.uploaded_files.clear()
                raw_uploaded = data["uploaded_files"] or {}
                for pid, entries in raw_uploaded.items():
                    clean_entries = []
                    for entry in entries or []:
                        clean_entries.append({
                            "id": str(entry.get("id", "")),
                            "filename": str(entry.get("filename", "")),
                            "size": int(entry.get("size", 0) or 0),
                            "disk_path": str(entry.get("disk_path", "")),
                            # Backward compatibility: old snapshots may use dismissed=true
                            # to represent "already acknowledged by host".
                            "seen_by_host": bool(entry.get("seen_by_host", entry.get("dismissed", False))),
                        })
                    self.uploaded_files[str(pid)] = clean_entries
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
            if "slides_viewed" in data:
                self.slides_viewed = list(data.get("slides_viewed") or [])
            if "gdrive_url" in data:
                self.gdrive_url = data["gdrive_url"]
            if "talk_presentation_name" in data:
                self.talk_presentation_name = data["talk_presentation_name"]
            if "talk_presentation_url" in data:
                self.talk_presentation_url = data["talk_presentation_url"]
            if "talk_presentation_slug" in data:
                self.talk_presentation_slug = data["talk_presentation_slug"]

    def add_paste(self, pid: str, text: str) -> dict | None:
        entries = self.paste_texts.setdefault(pid, [])
        if len(entries) >= 10:
            return None
        entry = {"id": str(uuid.uuid4()), "text": text}
        entries.append(entry)
        return entry

    def add_uploaded_file(
        self,
        pid: str,
        file_id: str,
        filename: str,
        size: int,
        disk_path: str,
    ) -> dict:
        with self._lock:
            entries = self.uploaded_files.setdefault(pid, [])
            normalized_id = str(file_id)
            for entry in entries:
                if str(entry.get("id")) == normalized_id:
                    entry["filename"] = filename
                    entry["size"] = int(size)
                    entry["disk_path"] = disk_path
                    # Keep seen status if already acknowledged on this file id.
                    entry["seen_by_host"] = bool(entry.get("seen_by_host", False))
                    return dict(entry)
            created = {
                "id": normalized_id,
                "filename": filename,
                "size": int(size),
                "disk_path": disk_path,
                "seen_by_host": False,
            }
            entries.append(created)
            return dict(created)

    def mark_uploaded_file_seen(self, target_uuid: str, file_id: str) -> bool:
        with self._lock:
            entries = self.uploaded_files.get(target_uuid, [])
            for entry in entries:
                if str(entry.get("id")) == str(file_id):
                    entry["seen_by_host"] = True
                    return True
            return False

    def visible_uploaded_files(self, pid: str) -> list[dict]:
        with self._lock:
            entries = self.uploaded_files.get(pid, [])
            return [dict(e) for e in entries]

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
            "uploaded_files": {k: [dict(e) for e in v] for k, v in self.uploaded_files.items()},
            "slides_viewed": [dict(sv) for sv in self.slides_viewed],
        }

    def reset_for_new_session(self) -> None:
        """Reset session-scoped misc runtime state when a new session starts."""
        with self._lock:
            self.paste_texts.clear()
            self.uploaded_files.clear()
            self.notes_content = None
            self.summary_points = []
            self.summary_raw_markdown = None
            self.summary_updated_at = None
            # slides_cache_status is NOT cleared — it's infrastructure state
            # (PDF cache + PPTX file timestamps) that survives session changes.
            self.slides_current = None
            self.slides_viewed = []
            self.gdrive_url = None
            self.talk_presentation_name = None
            self.talk_presentation_url = None
            self.talk_presentation_slug = None


misc_state = MiscState()
