import threading


class MiscState:
    def __init__(self):
        self._lock = threading.Lock()
        self.paste_texts: dict[str, list[dict]] = {}  # uuid → [{id, text}]
        self.paste_next_id: int = 0
        self.feedback_pending: list[str] = []
        self.notes_content: str | None = None
        self.summary_points: list[dict] = []
        self.summary_raw_markdown: str | None = None
        self.summary_updated_at: str | None = None  # ISO string
        self.slides_cache_status: dict[str, dict] = {}

    def sync_from_restore(self, data: dict):
        with self._lock:
            if "paste_texts" in data:
                self.paste_texts.clear()
                self.paste_texts.update(data["paste_texts"])
            if "paste_next_id" in data:
                self.paste_next_id = data["paste_next_id"]
            if "feedback_pending" in data:
                self.feedback_pending.clear()
                self.feedback_pending.extend(data["feedback_pending"])
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

    def add_paste(self, pid: str, text: str) -> dict | None:
        entries = self.paste_texts.setdefault(pid, [])
        if len(entries) >= 10:
            return None
        self.paste_next_id += 1
        entry = {"id": self.paste_next_id, "text": text}
        entries.append(entry)
        return entry

    def dismiss_paste(self, target_uuid: str, paste_id: int) -> bool:
        if target_uuid not in self.paste_texts:
            return False
        self.paste_texts[target_uuid] = [
            e for e in self.paste_texts[target_uuid] if e["id"] != paste_id
        ]
        if not self.paste_texts[target_uuid]:
            del self.paste_texts[target_uuid]
        return True

    def add_feedback(self, text: str):
        self.feedback_pending.append(text)

    def snapshot(self) -> dict:
        return {
            "paste_texts": {k: list(v) for k, v in self.paste_texts.items()},
            "paste_next_id": self.paste_next_id,
            "feedback_pending": list(self.feedback_pending),
        }


misc_state = MiscState()
