"""Pydantic models for WebSocket messages sent to participants and the host browser.

Source of truth: docs/participant-ws.yaml and docs/host-ws.yaml (AsyncAPI specs).
The contract test in tests/daemon/test_ws_contract.py validates these registries
against those YAML files — keep them in sync.

Usage:
    from daemon.ws_messages import PARTICIPANT_MESSAGES, HOST_MESSAGES
"""
from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel


# ── Slides ────────────────────────────────────────────────────────────────────

class SlidesCurrentMsg(BaseModel):
    type: Literal["slides_current"] = "slides_current"
    slides_current: Optional[dict[str, Any]] = None


class SlidesCacheStatusMsg(BaseModel):
    type: Literal["slides_cache_status"] = "slides_cache_status"
    slides_cache_status: Optional[dict[str, Any]] = None


# ── Activity ──────────────────────────────────────────────────────────────────

class ActivityUpdatedMsg(BaseModel):
    type: Literal["activity_updated"] = "activity_updated"
    current_activity: str


# ── Identity / Participants ───────────────────────────────────────────────────

class ParticipantUpdatedParticipantMsg(BaseModel):
    """Participant-only: count only."""
    type: Literal["participant_updated"] = "participant_updated"
    count: int


class ParticipantUpdatedHostMsg(BaseModel):
    """Host-only: count + full participant list."""
    type: Literal["participant_updated"] = "participant_updated"
    count: int
    participants: list[dict[str, Any]]  # [{uuid, name, score, location, avatar}]


# ── Poll ──────────────────────────────────────────────────────────────────────

class PollOpenedMsg(BaseModel):
    type: Literal["poll_opened"] = "poll_opened"
    poll: dict[str, Any]  # {id, question, options[], multi}


class PollClosedMsg(BaseModel):
    type: Literal["poll_closed"] = "poll_closed"


class PollCorrectRevealedMsg(BaseModel):
    type: Literal["poll_correct_revealed"] = "poll_correct_revealed"
    correct_ids: list[str]


class PollClearedMsg(BaseModel):
    type: Literal["poll_cleared"] = "poll_cleared"


class PollTimerStartedMsg(BaseModel):
    type: Literal["poll_timer_started"] = "poll_timer_started"
    seconds: int


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
    language: Optional[str] = None


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
    statement: Optional[str] = None
    phase: Optional[str] = None
    sides: dict[str, str] = {}
    arguments: list[dict[str, Any]] = []
    champions: dict[str, str] = {}
    auto_assigned: list[str] = []
    first_side: Optional[str] = None
    round_index: Optional[int] = None
    round_timer_seconds: Optional[int] = None
    round_timer_started_at: Optional[str] = None


class DebateTimerMsg(BaseModel):
    type: Literal["debate_timer"] = "debate_timer"
    round_index: int
    seconds: int
    started_at: Optional[str] = None


class DebateRoundEndedMsg(BaseModel):
    type: Literal["debate_round_ended"] = "debate_round_ended"


# ── Leaderboard ───────────────────────────────────────────────────────────────

class LeaderboardRevealedMsg(BaseModel):
    """Same structure for both participants and host: positions [{rank, name, score, avatar}]."""
    type: Literal["leaderboard_revealed"] = "leaderboard_revealed"
    positions: list[dict[str, Any]]


# ── Quiz ──────────────────────────────────────────────────────────────────────

class QuizStatusMsg(BaseModel):
    """Same structure for both participants and host."""
    type: Literal["quiz_status"] = "quiz_status"
    status: str
    message: str


class QuizPreviewMsg(BaseModel):
    """Same structure for both participants and host."""
    type: Literal["quiz_preview"] = "quiz_preview"
    question: str
    options: list[Any]
    multi: bool
    correct_indices: list[int]


# ── Host-only: Poll vote tally ────────────────────────────────────────────────

class VoteUpdateMsg(BaseModel):
    type: Literal["vote_update"] = "vote_update"
    votes: dict[str, int]  # option_id → count


# ── Host-only: Emoji ──────────────────────────────────────────────────────────

class EmojiReactionMsg(BaseModel):
    type: Literal["emoji_reaction"] = "emoji_reaction"
    emoji: str


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


# ── Registries ────────────────────────────────────────────────────────────────

PARTICIPANT_MESSAGES: dict[str, type[BaseModel]] = {
    # Slides
    "slides_current": SlidesCurrentMsg,
    "slides_cache_status": SlidesCacheStatusMsg,
    # Activity
    "activity_updated": ActivityUpdatedMsg,
    # Identity
    "participant_updated": ParticipantUpdatedParticipantMsg,
    # Poll
    "poll_opened": PollOpenedMsg,
    "poll_closed": PollClosedMsg,
    "poll_correct_revealed": PollCorrectRevealedMsg,
    "poll_cleared": PollClearedMsg,
    "poll_timer_started": PollTimerStartedMsg,
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
    # Quiz
    "quiz_status": QuizStatusMsg,
    "quiz_preview": QuizPreviewMsg,
}

HOST_MESSAGES: dict[str, type[BaseModel]] = {
    # Poll
    "vote_update": VoteUpdateMsg,
    # Word Cloud
    "wordcloud_updated": WordcloudUpdatedMsg,
    # Q&A
    "qa_updated": QaUpdatedMsg,
    # Code Review
    "codereview_selections_updated": CodereviewSelectionsUpdatedMsg,
    # Emoji
    "emoji_reaction": EmojiReactionMsg,
    # Quiz
    "quiz_status": QuizStatusMsg,
    "quiz_preview": QuizPreviewMsg,
    # Leaderboard
    "leaderboard_revealed": LeaderboardRevealedMsg,
    # Paste & Upload
    "paste_received": PasteReceivedMsg,
    "file_uploaded": FileUploadedMsg,
    # Participants
    "participant_updated": ParticipantUpdatedHostMsg,
}
