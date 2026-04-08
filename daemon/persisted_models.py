"""Pydantic models for JSON payloads persisted by the daemon."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class PersistedParticipant(PersistedModel):
    """Participant identity persisted in session snapshots."""

    name: str | None = None
    avatar: str | None = None
    score: int | float | None = None
    location: str | None = None


class PersistedSessionState(PersistedModel):
    """Runtime session snapshot persisted in `session-state.json`."""

    session_id: str | None = None
    session_name: str | None = None
    saved_at: str | None = None
    mode: str | None = None
    activity: str | None = None
    current_activity: str | None = None

    participants: dict[str, PersistedParticipant] = Field(default_factory=dict)
    # Legacy split maps: accepted on read, omitted on write.
    participant_names: dict[str, str] = Field(default_factory=dict, exclude=True)
    participant_avatars: dict[str, str] = Field(default_factory=dict, exclude=True)
    participant_universes: dict[str, str] = Field(default_factory=dict, exclude=True)
    scores: dict[str, int | float] = Field(default_factory=dict, exclude=True)
    locations: dict[str, str] = Field(default_factory=dict, exclude=True)

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

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_participant_maps(_cls, value):
        if not isinstance(value, dict):
            return value

        data = dict(value)
        participants_raw = data.get("participants")
        participants: dict[str, dict[str, Any]] = {}
        if isinstance(participants_raw, dict):
            for pid, entry in participants_raw.items():
                pid_str = str(pid)
                if isinstance(entry, PersistedParticipant):
                    participants[pid_str] = entry.model_dump(mode="json", exclude_unset=True)
                elif isinstance(entry, dict):
                    participants[pid_str] = dict(entry)

        names = data.get("participant_names") if isinstance(data.get("participant_names"), dict) else {}
        avatars = data.get("participant_avatars") if isinstance(data.get("participant_avatars"), dict) else {}
        scores = data.get("scores") if isinstance(data.get("scores"), dict) else {}
        locations = data.get("locations") if isinstance(data.get("locations"), dict) else {}

        all_ids = set(participants) | {str(pid) for pid in names} | {str(pid) for pid in avatars}
        all_ids |= {str(pid) for pid in scores} | {str(pid) for pid in locations}
        for pid in all_ids:
            row = participants.get(pid, {})
            if not isinstance(row, dict):
                row = {}

            name = names.get(pid)
            if isinstance(name, str) and name:
                row.setdefault("name", name)

            avatar = avatars.get(pid)
            if isinstance(avatar, str) and avatar:
                row.setdefault("avatar", avatar)

            score = scores.get(pid)
            if isinstance(score, (int, float)):
                row.setdefault("score", score)

            location = locations.get(pid)
            if isinstance(location, str) and location:
                row.setdefault("location", location)

            participants[pid] = row

        data["participants"] = participants
        return data

    @field_validator("poll_correct_ids", mode="before")
    @classmethod
    def _normalize_poll_correct_ids(_cls, value):
        return [] if value is None else value
