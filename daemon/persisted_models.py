"""Pydantic models for JSON payloads persisted by the daemon."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PersistedModel(BaseModel):
    """Base persisted model: tolerate forward/backward-compatible extra fields."""

    model_config = ConfigDict(extra="allow")


class PersistedSessionRef(PersistedModel):
    """Session entry persisted in global-state legacy formats."""

    name: str | None = None
    started_at: str | None = None
    status: str | None = None
    ended_at: str | None = None
    paused_intervals: list[dict[str, Any]] = Field(default_factory=list)


class PersistedGlobalState(PersistedModel):
    """Global daemon state persisted in `global-state.json`."""

    active_session_id: str | None = None
    session_id: str | None = None
    log_level: str | None = None
    main: PersistedSessionRef | None = None
    talk: PersistedSessionRef | None = None
    stack: list[PersistedSessionRef] | None = None


class PersistedSessionMeta(PersistedModel):
    """Session metadata subset persisted in `session-state.json`."""

    session_id: str | None = None
    started_at: str | None = None
    paused_intervals: list[dict[str, Any]] = Field(default_factory=list)
    talk: PersistedSessionRef | None = None


class PersistedSessionState(PersistedModel):
    """Runtime session snapshot persisted in `session-state.json`."""

    session_id: str | None = None
    session_name: str | None = None
    saved_at: str | None = None
    mode: str | None = None
    activity: str | None = None
    current_activity: str | None = None

    participants: dict[str, dict[str, Any]] = Field(default_factory=dict)
    participant_names: dict[str, str] = Field(default_factory=dict)
    participant_avatars: dict[str, str] = Field(default_factory=dict)
    participant_universes: dict[str, str] = Field(default_factory=dict)
    scores: dict[str, int | float] = Field(default_factory=dict)
    locations: dict[str, str] = Field(default_factory=dict)

    poll: dict[str, Any] | None = None
    poll_active: bool | None = None
    poll_correct_ids: list[str] = Field(default_factory=list)
    poll_opened_at: str | None = None
    poll_timer_seconds: int | None = None
    poll_timer_started_at: str | None = None
    votes: dict[str, Any] = Field(default_factory=dict)

    qa: dict[str, Any] | None = None
    qa_questions: dict[str, dict[str, Any]] = Field(default_factory=dict)

    wordcloud: dict[str, Any] | None = None
    wordcloud_words: dict[str, int] = Field(default_factory=dict)
    wordcloud_word_order: list[str] = Field(default_factory=list)
    wordcloud_topic: str | None = None

    codereview: dict[str, Any] | None = None
    codereview_snippet: str | None = None
    codereview_language: str | None = None
    codereview_phase: str | None = None
    codereview_selections: dict[str, list[int]] = Field(default_factory=dict)
    codereview_confirmed: list[int] = Field(default_factory=list)

    debate: dict[str, Any] | None = None
    debate_statement: str | None = None
    debate_phase: str | None = None
    debate_sides: dict[str, str] = Field(default_factory=dict)
    debate_arguments: list[dict[str, Any]] = Field(default_factory=list)
    debate_champions: dict[str, str] = Field(default_factory=dict)
    debate_auto_assigned: list[str] = Field(default_factory=list)
    debate_first_side: str | None = None
    debate_round_index: int | None = None
    debate_round_timer_seconds: int | None = None
    debate_round_timer_started_at: str | None = None

    slides_current: dict[str, Any] | None = None
    summary_points: list[dict[str, Any]] = Field(default_factory=list)
    leaderboard_active: bool | None = None
    token_usage: dict[str, Any] | None = None

    @field_validator("poll_correct_ids", mode="before")
    @classmethod
    def _normalize_poll_correct_ids(_cls, value):
        return [] if value is None else value
