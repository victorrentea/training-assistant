"""Pydantic models for WebSocket messages sent to participants and the host browser.

Source of truth: docs/participant-ws.yaml and docs/host-ws.yaml (AsyncAPI specs).
The contract test in tests/daemon/test_ws_contract.py validates these registries
against those YAML files — keep them in sync.

Usage:
    from daemon.ws_messages import PARTICIPANT_MESSAGES, HOST_MESSAGES
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from daemon.slides.models import CurrentSlide, Deck

# ── Slides ────────────────────────────────────────────────────────────────────

class SlidesCurrentMsg(BaseModel):
    type: Literal["current_slide_updated"] = "current_slide_updated"
    current_slide: CurrentSlide


class DecksUpdatedMsg(BaseModel):
    type: Literal["decks_updated"] = "decks_updated"
    decks: dict[str, Deck] = {}


# ── Activity ──────────────────────────────────────────────────────────────────

class ActivityUpdatedMsg(BaseModel):
    type: Literal["activity_updated"] = "activity_updated"
    current_activity: str


# ── Identity / Participants ───────────────────────────────────────────────────

class ActiveParticipantsCountUpdatedMsg(BaseModel):
    """Participant-only: total known non-host participant count."""
    type: Literal["active_participants_count_updated"] = "active_participants_count_updated"
    count: int


class SlidesHistoryCountUpdatedMsg(BaseModel):
    """Participant-only: total number of tracked viewed slides."""
    type: Literal["slides_history_updated"] = "slides_history_updated"
    count: int


class ParticipantListUpdatedMsg(BaseModel):
    """Host-only: full participant list."""
    type: Literal["participant_list_updated"] = "participant_list_updated"
    participants: list[dict[str, Any]]  # [{uuid, name, score, location, avatar, engagement, last_active_at, last_view}]


# ── Quiz ──────────────────────────────────────────────────────────────────────

class QuizQueueUpdatedMsg(BaseModel):
    type: Literal["quiz_queue_updated"] = "quiz_queue_updated"


class QuizOpenedMsg(BaseModel):
    type: Literal["quiz_opened"] = "quiz_opened"
    quiz: dict[str, Any]  # {id, question, options[], multi}


class QuizEndedMsg(BaseModel):
    type: Literal["quiz_ended"] = "quiz_ended"


class QuizCorrectRevealedMsg(BaseModel):
    type: Literal["quiz_correct_revealed"] = "quiz_correct_revealed"
    correct_indices: list[int]


class QuizClearedMsg(BaseModel):
    type: Literal["quiz_cleared"] = "quiz_cleared"


# ── Poll ──────────────────────────────────────────────────────────────────────

class PollOpenedMsg(BaseModel):
    """Bare signal — fires once on Start. Participant resets per-session
    vote tracking. WS order guarantees PollUpdatedMsg arrives next with
    the actual snapshot."""
    type: Literal["poll_opened"] = "poll_opened"


class PollUpdatedMsg(BaseModel):
    """Participant-facing snapshot. Fires on Start, host edits, Stop, and
    participant votes when public=true. `counts` present when the poll is
    public OR has been ended (read-only results); absent → participant
    hides per-option bars. `ended=True` flips the participant UI to a
    read-only results view that lingers until Clear."""
    type: Literal["poll_updated"] = "poll_updated"
    poll: dict[str, Any]              # {question, options, multi, public}
    counts: list[int] | None = None
    ended: bool = False


class PollHostUpdateMsg(BaseModel):
    """Host-only snapshot (sent via notify_host). Always carries full
    counts regardless of public flag. `poll` is None when the draft was
    cleared; `started` reflects whether the poll is currently live;
    `ended` is True once the poll has been stopped but not yet cleared
    (host UI locks edits and keeps showing the results)."""
    type: Literal["poll_host_update"] = "poll_host_update"
    poll: dict[str, Any] | None = None
    started: bool = False
    ended: bool = False
    counts: list[int] = []
    voted_count: int = 0
    participant_counts: list[int] = []   # real-participant counts only (per option)
    host_extras: list[int] = []          # host-added extras (per option); total = participant + extras


class QuizEndCountdownStartedMsg(BaseModel):
    type: Literal["quiz_end_countdown_started"] = "quiz_end_countdown_started"
    seconds: int
    started_at: str


# ── Scores ────────────────────────────────────────────────────────────────────

class ScoresUpdatedMsg(BaseModel):
    type: Literal["scores_updated"] = "scores_updated"
    scores: dict[str, int]  # uuid → score


# ── Word Cloud ────────────────────────────────────────────────────────────────

class WordcloudUpdatedMsg(BaseModel):
    """Same structure for both participants and host."""
    type: Literal["wordcloud_updated"] = "wordcloud_updated"
    words: dict[str, int]   # word → count
    word_order: list[str]
    topic: str


# ── Q&A ───────────────────────────────────────────────────────────────────────

class QaUpdatedMsg(BaseModel):
    """Same structure for both participants and host."""
    type: Literal["qa_updated"] = "qa_updated"
    questions: list[dict[str, Any]]


# ── Code Review ───────────────────────────────────────────────────────────────

class CodereviewOpenedMsg(BaseModel):
    type: Literal["codereview_opened"] = "codereview_opened"
    snippet: str
    language: str | None = None


class CodereviewSelectionClosedMsg(BaseModel):
    type: Literal["codereview_selection_closed"] = "codereview_selection_closed"


class CodereviewLineConfirmedMsg(BaseModel):
    type: Literal["codereview_line_confirmed"] = "codereview_line_confirmed"
    line: int


class CodereviewClearedMsg(BaseModel):
    type: Literal["codereview_cleared"] = "codereview_cleared"


class CodereviewSelectionsUpdatedMsg(BaseModel):
    """Host-only: aggregate line selection counts."""
    type: Literal["codereview_selections_updated"] = "codereview_selections_updated"
    line_counts: dict[str, int]  # line → count


# ── Debate ────────────────────────────────────────────────────────────────────

class DebateUpdatedMsg(BaseModel):
    """Full debate state snapshot broadcast to participants."""
    type: Literal["debate_updated"] = "debate_updated"
    statement: str | None = None
    phase: str | None = None
    sides: dict[str, str] = {}
    arguments: list[dict[str, Any]] = []
    champions: dict[str, str] = {}
    auto_assigned: list[str] = []
    first_side: str | None = None
    round_index: int | None = None
    round_timer_seconds: int | None = None
    round_timer_started_at: str | None = None


class DebateTimerMsg(BaseModel):
    type: Literal["debate_timer"] = "debate_timer"
    round_index: int
    seconds: int
    started_at: str | None = None


class DebateRoundEndedMsg(BaseModel):
    type: Literal["debate_round_ended"] = "debate_round_ended"


# ── Leaderboard ───────────────────────────────────────────────────────────────

class LeaderboardRevealedMsg(BaseModel):
    """Same structure for both participants and host: positions [{rank, name, score, avatar}]."""
    type: Literal["leaderboard_revealed"] = "leaderboard_revealed"
    positions: list[dict[str, Any]]


# ── Host-only: Quiz vote tally ────────────────────────────────────────────────

class VoteUpdateMsg(BaseModel):
    type: Literal["vote_update"] = "vote_update"
    voted_count: int


# ── Host-only: Emoji ──────────────────────────────────────────────────────────

class EmojiReactionMsg(BaseModel):
    type: Literal["emoji_reaction"] = "emoji_reaction"
    emoji: str


class EmojiCountersUpdatedMsg(BaseModel):
    """Cumulative emoji reaction counts broadcast to all talk-mode participants."""
    type: Literal["emoji_counters_updated"] = "emoji_counters_updated"
    counters: dict[str, int]


# ── Host-only: Addon bridge status ────────────────────────────────────────────

class OverlayConnectedMsg(BaseModel):
    type: Literal["overlay_connected"] = "overlay_connected"
    overlay_connected: bool


# ── Host-only: Paste & Upload ─────────────────────────────────────────────────

class PasteReceivedMsg(BaseModel):
    type: Literal["paste_received"] = "paste_received"
    uuid: str
    id: str
    text: str


class FileUploadedMsg(BaseModel):
    type: Literal["file_uploaded"] = "file_uploaded"
    uuid: str
    id: str
    filename: str
    size: int
    disk_path: str


# ── Notes & Summary ───────────────────────────────────────────────────────────

class NotesUpdatedMsg(BaseModel):
    type: Literal["notes_updated"] = "notes_updated"
    updated_at: str | None = None  # ISO timestamp of notes file mtime


class SummaryUpdatedMsg(BaseModel):
    type: Literal["summary_updated"] = "summary_updated"
    updated_at: str | None = None  # ISO timestamp of ai-summary.md mtime


# ── Host-only: Talk presentation ──────────────────────────────────────────────

class TalkPdfReadyMsg(BaseModel):
    type: Literal["talk_pdf_ready"] = "talk_pdf_ready"
    slug: str


class TalkPdfFailedMsg(BaseModel):
    type: Literal["talk_pdf_failed"] = "talk_pdf_failed"


# ── Addons inbound ───────────────────────────────────────────────────────────

class GitFileOpenedMsg(BaseModel):
    """Inbound message from macOS addon when user opens a file in IntelliJ."""
    type: Literal["git_file_opened"]
    url: str
    branch: str
    file: str
    file_url: str | None = None


# ── Cross-cutting ────────────────────────────────────────────────────────────

class ReloadMsg(BaseModel):
    type: Literal["reload"] = "reload"


# ── Registries ────────────────────────────────────────────────────────────────

PARTICIPANT_MESSAGES: dict[str, type[BaseModel]] = {
    # Slides
    "current_slide_updated": SlidesCurrentMsg,
    "decks_updated": DecksUpdatedMsg,
    # Activity
    "activity_updated": ActivityUpdatedMsg,
    # Identity
    "active_participants_count_updated": ActiveParticipantsCountUpdatedMsg,
    "slides_history_updated": SlidesHistoryCountUpdatedMsg,
    # Quiz
    "quiz_opened": QuizOpenedMsg,
    "quiz_ended": QuizEndedMsg,
    "quiz_correct_revealed": QuizCorrectRevealedMsg,
    "quiz_cleared": QuizClearedMsg,
    "quiz_end_countdown_started": QuizEndCountdownStartedMsg,
    # Poll
    "poll_opened": PollOpenedMsg,
    "poll_updated": PollUpdatedMsg,
    # Scores
    "scores_updated": ScoresUpdatedMsg,
    # Word Cloud
    "wordcloud_updated": WordcloudUpdatedMsg,
    # Q&A
    "qa_updated": QaUpdatedMsg,
    # Code Review
    "codereview_opened": CodereviewOpenedMsg,
    "codereview_selection_closed": CodereviewSelectionClosedMsg,
    "codereview_line_confirmed": CodereviewLineConfirmedMsg,
    "codereview_cleared": CodereviewClearedMsg,
    # Debate
    "debate_updated": DebateUpdatedMsg,
    "debate_timer": DebateTimerMsg,
    "debate_round_ended": DebateRoundEndedMsg,
    # Leaderboard
    "leaderboard_revealed": LeaderboardRevealedMsg,
    # Notes & Summary
    "notes_updated": NotesUpdatedMsg,
    "summary_updated": SummaryUpdatedMsg,
    # Emoji
    "emoji_counters_updated": EmojiCountersUpdatedMsg,
    # Cross-cutting
    "reload": ReloadMsg,
}

HOST_MESSAGES: dict[str, type[BaseModel]] = {
    # Slides
    "decks_updated": DecksUpdatedMsg,
    # Quiz
    "quiz_queue_updated": QuizQueueUpdatedMsg,
    "vote_update": VoteUpdateMsg,
    # Poll
    "poll_host_update": PollHostUpdateMsg,
    # Word Cloud
    "wordcloud_updated": WordcloudUpdatedMsg,
    # Q&A
    "qa_updated": QaUpdatedMsg,
    # Code Review
    "codereview_selections_updated": CodereviewSelectionsUpdatedMsg,
    # Emoji
    "emoji_reaction": EmojiReactionMsg,
    # Paste & Upload
    "paste_received": PasteReceivedMsg,
    "file_uploaded": FileUploadedMsg,
    # Participants
    "participant_list_updated": ParticipantListUpdatedMsg,
    # Notes & Summary
    "notes_updated": NotesUpdatedMsg,
    "summary_updated": SummaryUpdatedMsg,
    # Talk presentation
    "talk_pdf_ready": TalkPdfReadyMsg,
    "talk_pdf_failed": TalkPdfFailedMsg,
    # Cross-cutting
    "reload": ReloadMsg,
}

# Feature-classification metadata used by docs generators.
# Keep these maps in sync with PARTICIPANT_MESSAGES / HOST_MESSAGES.
PARTICIPANT_MESSAGE_FEATURES: dict[str, str] = {
    # Slides
    "current_slide_updated": "slides",
    "decks_updated": "slides",
    # Activity
    "activity_updated": "activity",
    # Identity
    "active_participants_count_updated": "identity",
    "slides_history_updated": "slides",
    # Quiz
    "quiz_opened": "quiz",
    "quiz_ended": "quiz",
    "quiz_correct_revealed": "quiz",
    "quiz_cleared": "quiz",
    "quiz_end_countdown_started": "quiz",
    # Poll
    "poll_opened": "poll",
    "poll_updated": "poll",
    # Scores & Leaderboard
    "scores_updated": "scores_leaderboard",
    "leaderboard_revealed": "scores_leaderboard",
    # Word Cloud
    "wordcloud_updated": "wordcloud",
    # Q&A
    "qa_updated": "qa",
    # Code Review
    "codereview_opened": "codereview",
    "codereview_selection_closed": "codereview",
    "codereview_line_confirmed": "codereview",
    "codereview_cleared": "codereview",
    # Debate
    "debate_updated": "debate",
    "debate_timer": "debate",
    "debate_round_ended": "debate",
    # Notes & Summary
    "notes_updated": "notes_summary",
    "summary_updated": "notes_summary",
    # Emoji
    "emoji_counters_updated": "emoji",
    # Cross-cutting
    "reload": "reload",
}

HOST_MESSAGE_FEATURES: dict[str, str] = {
    # Slides
    "decks_updated": "slides",
    # Quiz
    "quiz_queue_updated": "quiz",
    "vote_update": "quiz",
    # Poll
    "poll_host_update": "poll",
    # Word Cloud
    "wordcloud_updated": "wordcloud",
    # Q&A
    "qa_updated": "qa",
    # Code Review
    "codereview_selections_updated": "codereview",
    # Emoji
    "emoji_reaction": "emoji",
    # Paste & Upload
    "paste_received": "paste_upload",
    "file_uploaded": "paste_upload",
    # Identity
    "participant_list_updated": "identity",
    # Notes & Summary
    "notes_updated": "notes_summary",
    "summary_updated": "notes_summary",
    # Talk presentation
    "talk_pdf_ready": "slides",
    "talk_pdf_failed": "slides",
    # Cross-cutting
    "reload": "reload",
}
