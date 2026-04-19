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

# ── Slides ────────────────────────────────────────────────────────────────────

class SlidesCurrentMsg(BaseModel):
    type: Literal["slides_current"] = "slides_current"
    slides_current: dict[str, Any] | None = None


class SlidesCacheStatusMsg(BaseModel):
    type: Literal["slides_updated"] = "slides_updated"
    refreshed_slugs: list[str] = []


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
    type: Literal["slides_history_count_updated"] = "slides_history_count_updated"
    count: int


class ParticipantListUpdatedMsg(BaseModel):
    """Host-only: full participant list."""
    type: Literal["participant_list_updated"] = "participant_list_updated"
    participants: list[dict[str, Any]]  # [{uuid, name, score, location, avatar}]


# ── Poll ──────────────────────────────────────────────────────────────────────

class PollQueueUpdatedMsg(BaseModel):
    type: Literal["poll_queue_updated"] = "poll_queue_updated"


class PollOpenedMsg(BaseModel):
    type: Literal["poll_opened"] = "poll_opened"
    poll: dict[str, Any]  # {id, question, options[], multi}


class PollEndedMsg(BaseModel):
    type: Literal["poll_ended"] = "poll_ended"
    vote_counts: list[int]


class PollCorrectRevealedMsg(BaseModel):
    type: Literal["poll_correct_revealed"] = "poll_correct_revealed"
    correct_indices: list[int]


class PollClearedMsg(BaseModel):
    type: Literal["poll_cleared"] = "poll_cleared"


class PollEndCountdownStartedMsg(BaseModel):
    type: Literal["poll_end_countdown_started"] = "poll_end_countdown_started"
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


# ── Host-only: Poll vote tally ────────────────────────────────────────────────

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


# ── Cross-cutting ────────────────────────────────────────────────────────────

class ReloadMsg(BaseModel):
    type: Literal["reload"] = "reload"


# ── Registries ────────────────────────────────────────────────────────────────

PARTICIPANT_MESSAGES: dict[str, type[BaseModel]] = {
    # Slides
    "slides_current": SlidesCurrentMsg,
    "slides_updated": SlidesCacheStatusMsg,
    # Activity
    "activity_updated": ActivityUpdatedMsg,
    # Identity
    "active_participants_count_updated": ActiveParticipantsCountUpdatedMsg,
    "slides_history_count_updated": SlidesHistoryCountUpdatedMsg,
    # Poll
    "poll_opened": PollOpenedMsg,
    "poll_ended": PollEndedMsg,
    "poll_correct_revealed": PollCorrectRevealedMsg,
    "poll_cleared": PollClearedMsg,
    "poll_end_countdown_started": PollEndCountdownStartedMsg,
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
    "slides_updated": SlidesCacheStatusMsg,
    # Poll
    "poll_queue_updated": PollQueueUpdatedMsg,
    "vote_update": VoteUpdateMsg,
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
    "slides_current": "slides",
    "slides_updated": "slides",
    # Activity
    "activity_updated": "activity",
    # Identity
    "active_participants_count_updated": "identity",
    "slides_history_count_updated": "slides",
    # Poll
    "poll_opened": "poll",
    "poll_ended": "poll",
    "poll_correct_revealed": "poll",
    "poll_cleared": "poll",
    "poll_end_countdown_started": "poll",
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
    "slides_updated": "slides",
    # Poll
    "poll_queue_updated": "poll",
    "vote_update": "poll",
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
