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
        self.poll: Optional[dict] = None
        self.poll_active: bool = False
        self.votes: dict[str, str] = {}
        self.participants: dict[str, WebSocket] = {}
        self.participant_names: dict[str, str] = {}  # uuid -> display_name
        self.participant_avatars: dict[str, str] = {}
        self.locations: dict[str, str] = {}
        self.quiz_request: Optional[dict] = None
        self.quiz_refine_request: Optional[dict] = None
        self.quiz_status: Optional[dict] = None
        self.daemon_last_seen: Optional[datetime] = None
        self.daemon_session_folder: Optional[str] = None
        self.daemon_session_notes: Optional[str] = None
        self.notes_content: Optional[str] = None
        self.quiz_preview: Optional[dict] = None
        self.scores: dict[str, int] = {}
        self.base_scores: dict[str, int] = {}
        self.poll_opened_at: Optional[datetime] = None
        self.vote_times: dict[str, datetime] = {}
        self.current_activity: ActivityType = ActivityType.NONE
        self.wordcloud_words: dict[str, int] = {}
        self.wordcloud_topic: str = ""
        self.qa_questions: dict[str, dict] = {}
        # Each value: { id, text, author, upvoters: set[str], answered: bool, timestamp: float }
        # Code Review state
        self.codereview_snippet: str | None = None
        self.codereview_language: str | None = None
        self.codereview_phase: str = "idle"  # "idle" | "selecting" | "reviewing"
        self.codereview_selections: dict[str, set[int]] = {}  # uuid → set of line numbers
        self.codereview_confirmed: set[int] = set()  # lines host confirmed
        self.summary_points: list[dict] = []
        self.summary_updated_at: Optional[datetime] = None
        self.summary_force_requested: bool = False
        # Debate state
        self.debate_statement: Optional[str] = None
        self.debate_phase: Optional[str] = None  # "side_selection"|"arguments"|"ai_cleanup"|"prep"|"live_debate"|"ended"
        self.debate_sides: dict[str, str] = {}  # uuid → "for"|"against"
        self.debate_arguments: list[dict] = []  # [{id, author_uuid, side, text, upvoters: set, ai_generated: bool, merged_into: str|None}]
        self.debate_champions: dict[str, str] = {}  # "for" → uuid, "against" → uuid
        self.debate_auto_assigned: set[str] = set()  # uuids that were auto-assigned a side

    def suggest_name(self) -> str:
        """Return the next available LOTR name (by popularity order).
        A name is 'taken' if any currently connected participant has it."""
        connected_names = {self.participant_names[uid] for uid in self.participants if uid in self.participant_names and uid != "__host__"}
        available = [n for n in LOTR_NAMES if n not in connected_names]
        return available[0] if available else f"Guest{random.randint(100, 999)}"

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


def get_avatar_filename(name: str) -> str:
    """Convert a LOTR name to its avatar filename slug."""
    return name.lower().replace(' ', '-') + '.png'


def assign_avatar(app_state: AppState, uuid: str, name: str) -> str:
    """Assign avatar based on name. LOTR names always get their matching avatar
    (even if duplicated). Custom names get a unique avatar based on UUID hash."""
    # LOTR name → always match character avatar (no dedup, avoids name/avatar mismatch)
    if name in LOTR_NAMES:
        avatar = get_avatar_filename(name)
        app_state.participant_avatars[uuid] = avatar
        return avatar
    # Custom name: assign-once, deduplicated
    if uuid in app_state.participant_avatars:
        return app_state.participant_avatars[uuid]
    taken = set(app_state.participant_avatars.values())
    preferred_index = int(uuid.replace('-', ''), 16) % len(LOTR_NAMES)
    for offset in range(len(LOTR_NAMES)):
        avatar = get_avatar_filename(LOTR_NAMES[(preferred_index + offset) % len(LOTR_NAMES)])
        if avatar not in taken:
            app_state.participant_avatars[uuid] = avatar
            return avatar
    # All 30 taken — fall back to preferred
    avatar = get_avatar_filename(LOTR_NAMES[preferred_index])
    app_state.participant_avatars[uuid] = avatar
    return avatar
