from typing import Optional
from datetime import datetime
from fastapi import WebSocket
from enum import Enum
import random


class ActivityType(str, Enum):
    NONE = "none"
    POLL = "poll"
    WORDCLOUD = "wordcloud"
    QA = "qa"

LOTR_NAMES = [
    "Frodo", "Samwise", "Gandalf", "Aragorn", "Legolas", "Gimli", "Boromir",
    "Merry", "Pippin", "Galadriel", "Elrond", "Saruman", "Faramir",
    "Eowyn", "Theoden", "Treebeard", "Bilbo", "Thorin", "Smaug", "Gollum",
    "Radagast", "Tom Bombadil", "Glorfindel", "Celeborn", "Arwen", "Eomer",
    "Haldir", "Shadowfax", "Grima Wormtongue", "The One Ring"
]


class AppState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.poll: Optional[dict] = None
        self.poll_active: bool = False
        self.votes: dict[str, str] = {}
        self.participants: dict[str, WebSocket] = {}
        self.suggested_names: set[str] = set()
        self.locations: dict[str, str] = {}
        self.quiz_request: Optional[dict] = None
        self.quiz_refine_request: Optional[dict] = None
        self.quiz_status: Optional[dict] = None
        self.daemon_last_seen: Optional[datetime] = None
        self.quiz_preview: Optional[dict] = None
        self.scores: dict[str, int] = {}
        self.base_scores: dict[str, int] = {}
        self.poll_opened_at: Optional[datetime] = None
        self.vote_times: dict[str, datetime] = {}
        self.current_activity: ActivityType = ActivityType.NONE
        self.wordcloud_words: dict[str, int] = {}
        self.qa_questions: dict[str, dict] = {}
        # Each value: { id, text, author, upvoters: set[str], answered: bool, timestamp: float }

    def suggest_name(self) -> str:
        # Purge stale suggestions older than connected participants set (keep set bounded)
        if len(self.suggested_names) > 50:
            self.suggested_names.clear()
        taken = set(self.participants.keys()) | self.suggested_names
        available = [n for n in LOTR_NAMES if n not in taken]
        name = available[0] if available else f"Guest{random.randint(100, 999)}"
        self.suggested_names.add(name)
        return name

    def vote_counts(self) -> dict:
        if not self.poll:
            return {}
        counts = {opt["id"]: 0 for opt in self.poll["options"]}
        for selection in self.votes.values():
            ids = selection if isinstance(selection, list) else [selection]
            for option_id in ids:
                if option_id in counts:
                    counts[option_id] += 1
        return counts


state = AppState()
