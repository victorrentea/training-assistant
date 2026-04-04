"""Q&A state cache for daemon.

Owns the Q&A questions state. Initial data comes from daemon_state_push.
"""
import threading
import time
import uuid as uuid_mod


class QAState:
    """Q&A state. Mutation methods run on uvicorn's single-threaded
    event loop (no lock needed). sync_from_restore runs on the main thread
    and uses _lock for cross-thread safety.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.questions: dict[str, dict] = {}

    def sync_from_restore(self, data: dict):
        """Update from daemon_state_push. Called from main thread."""
        with self._lock:
            if "qa_questions" in data:
                self.questions.clear()
                for qid, q in data["qa_questions"].items():
                    self.questions[qid] = {
                        **q,
                        "upvoters": set(q.get("upvoters", [])),
                    }

    def submit(self, author: str, text: str) -> str:
        """Submit a question. Returns the question ID."""
        qid = str(uuid_mod.uuid4())
        self.questions[qid] = {
            "id": qid,
            "text": text,
            "author": author,
            "upvoters": set(),
            "answered": False,
            "timestamp": time.time(),
        }
        return qid

    def upvote(self, qid: str, pid: str) -> tuple[bool, str | None]:
        """Upvote a question. Returns (success, author_pid)."""
        q = self.questions.get(qid)
        if not q or q["author"] == pid or pid in q["upvoters"]:
            return False, None
        q["upvoters"].add(pid)
        return True, q["author"]

    def edit_text(self, qid: str, text: str) -> bool:
        q = self.questions.get(qid)
        if not q:
            return False
        q["text"] = text
        return True

    def delete(self, qid: str) -> bool:
        return self.questions.pop(qid, None) is not None

    def toggle_answered(self, qid: str, answered: bool) -> bool:
        q = self.questions.get(qid)
        if not q:
            return False
        q["answered"] = answered
        return True

    def clear(self):
        self.questions.clear()

    def build_question_list_raw(self) -> list[dict]:
        """Build sorted question list for participant broadcast — raw UUIDs, no personalisation."""
        questions = []
        for qid, q in sorted(
            self.questions.items(),
            key=lambda item: (-len(item[1]["upvoters"]), item[1]["timestamp"]),
        ):
            questions.append({
                "id": qid,
                "text": q["text"],
                "author_uuid": q["author"],
                "upvoter_uuids": list(q["upvoters"]),
                "answered": q["answered"],
                "timestamp": q["timestamp"],
            })
        return questions

    def build_question_list(self, names: dict[str, str], avatars: dict[str, str]) -> list[dict]:
        """Build sorted question list for host — resolves names and avatars."""
        questions = []
        for qid, q in sorted(
            self.questions.items(),
            key=lambda item: (-len(item[1]["upvoters"]), item[1]["timestamp"]),
        ):
            questions.append({
                "id": qid,
                "text": q["text"],
                "author": names.get(q["author"], "Unknown"),
                "author_uuid": q["author"],
                "author_avatar": avatars.get(q["author"], ""),
                "upvoters": list(q["upvoters"]),
                "upvote_count": len(q["upvoters"]),
                "answered": q["answered"],
                "timestamp": q["timestamp"],
            })
        return questions


# Module-level singleton
qa_state = QAState()
