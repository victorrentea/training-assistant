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


class PersistedPollState(PersistedModel):
    """Poll snapshot persisted in session state."""

    definition: dict[str, Any] | None = None
    active: bool | None = None
    correct_ids: list[str] = Field(default_factory=list)
    opened_at: str | None = None
    timer_seconds: int | None = None
    timer_started_at: str | None = None
    votes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("correct_ids", mode="before")
    @classmethod
    def _normalize_correct_ids(_cls, value):
        return [] if value is None else value


class PersistedWordCloudState(PersistedModel):
    """Word cloud snapshot persisted in session state."""

    words: dict[str, int] = Field(default_factory=dict)
    word_order: list[str] = Field(default_factory=list)
    topic: str | None = None


class PersistedCodeReviewState(PersistedModel):
    """Code review snapshot persisted in session state."""

    snippet: str | None = None
    language: str | None = None
    phase: str | None = None
    selections: dict[str, list[int]] = Field(default_factory=dict)
    confirmed: list[int] = Field(default_factory=list)


class PersistedDebateState(PersistedModel):
    """Debate snapshot persisted in session state."""

    statement: str | None = None
    phase: str | None = None
    sides: dict[str, str] = Field(default_factory=dict)
    arguments: list[dict[str, Any]] = Field(default_factory=list)
    champions: dict[str, str] = Field(default_factory=dict)
    auto_assigned: list[str] = Field(default_factory=list)
    first_side: str | None = None
    round_index: int | None = None
    round_timer_seconds: int | None = None
    round_timer_started_at: str | None = None


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

    poll: PersistedPollState | None = None
    # Legacy flat poll fields: accepted on read, omitted on write.
    poll_active: bool | None = Field(default=None, exclude=True)
    poll_correct_ids: list[str] = Field(default_factory=list, exclude=True)
    poll_opened_at: str | None = Field(default=None, exclude=True)
    poll_timer_seconds: int | None = Field(default=None, exclude=True)
    poll_timer_started_at: str | None = Field(default=None, exclude=True)
    votes: dict[str, Any] = Field(default_factory=dict, exclude=True)

    qa: dict[str, Any] | None = None
    qa_questions: dict[str, dict[str, Any]] = Field(default_factory=dict)

    wordcloud: PersistedWordCloudState | None = None
    # Legacy flat word cloud fields: accepted on read, omitted on write.
    wordcloud_words: dict[str, int] = Field(default_factory=dict, exclude=True)
    wordcloud_word_order: list[str] = Field(default_factory=list, exclude=True)
    wordcloud_topic: str | None = Field(default=None, exclude=True)

    codereview: PersistedCodeReviewState | None = None
    # Legacy flat code review fields: accepted on read, omitted on write.
    codereview_snippet: str | None = Field(default=None, exclude=True)
    codereview_language: str | None = Field(default=None, exclude=True)
    codereview_phase: str | None = Field(default=None, exclude=True)
    codereview_selections: dict[str, list[int]] = Field(default_factory=dict, exclude=True)
    codereview_confirmed: list[int] = Field(default_factory=list, exclude=True)

    debate: PersistedDebateState | None = None
    # Legacy flat debate fields: accepted on read, omitted on write.
    debate_statement: str | None = Field(default=None, exclude=True)
    debate_phase: str | None = Field(default=None, exclude=True)
    debate_sides: dict[str, str] = Field(default_factory=dict, exclude=True)
    debate_arguments: list[dict[str, Any]] = Field(default_factory=list, exclude=True)
    debate_champions: dict[str, str] = Field(default_factory=dict, exclude=True)
    debate_auto_assigned: list[str] = Field(default_factory=list, exclude=True)
    debate_first_side: str | None = Field(default=None, exclude=True)
    debate_round_index: int | None = Field(default=None, exclude=True)
    debate_round_timer_seconds: int | None = Field(default=None, exclude=True)
    debate_round_timer_started_at: str | None = Field(default=None, exclude=True)

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
        poll_raw = data.get("poll")
        poll: dict[str, Any] = {}
        if isinstance(poll_raw, PersistedPollState):
            poll = poll_raw.model_dump(mode="json", exclude_unset=True)
        elif isinstance(poll_raw, dict):
            poll = dict(poll_raw)
            poll_keys = {
                "definition",
                "active",
                "correct_ids",
                "opened_at",
                "timer_seconds",
                "timer_started_at",
                "votes",
            }
            if not any(key in poll for key in poll_keys):
                poll = {"definition": dict(poll_raw)}
        legacy_poll_keys = (
            "poll",
            "poll_active",
            "poll_correct_ids",
            "poll_opened_at",
            "poll_timer_seconds",
            "poll_timer_started_at",
            "votes",
        )
        if "poll_active" in data:
            poll.setdefault("active", data["poll_active"])
        if "poll_correct_ids" in data:
            legacy_correct_ids = data["poll_correct_ids"]
            poll.setdefault("correct_ids", [] if legacy_correct_ids is None else legacy_correct_ids)
        if "poll_opened_at" in data:
            poll.setdefault("opened_at", data["poll_opened_at"])
        if "poll_timer_seconds" in data:
            poll.setdefault("timer_seconds", data["poll_timer_seconds"])
        if "poll_timer_started_at" in data:
            poll.setdefault("timer_started_at", data["poll_timer_started_at"])
        if "votes" in data:
            poll.setdefault("votes", data["votes"])
        if any(key in data for key in legacy_poll_keys):
            data["poll"] = poll

        wordcloud_raw = data.get("wordcloud")
        wordcloud: dict[str, Any] = {}
        if isinstance(wordcloud_raw, PersistedWordCloudState):
            wordcloud = wordcloud_raw.model_dump(mode="json", exclude_unset=True)
        elif isinstance(wordcloud_raw, dict):
            wordcloud = dict(wordcloud_raw)
        legacy_wordcloud_keys = (
            "wordcloud",
            "wordcloud_words",
            "wordcloud_word_order",
            "wordcloud_topic",
        )
        if "wordcloud_words" in data:
            wordcloud.setdefault("words", data["wordcloud_words"])
        if "wordcloud_word_order" in data:
            wordcloud.setdefault("word_order", data["wordcloud_word_order"])
        if "wordcloud_topic" in data:
            wordcloud.setdefault("topic", data["wordcloud_topic"])
        if any(key in data for key in legacy_wordcloud_keys):
            data["wordcloud"] = wordcloud

        codereview_raw = data.get("codereview")
        codereview: dict[str, Any] = {}
        if isinstance(codereview_raw, PersistedCodeReviewState):
            codereview = codereview_raw.model_dump(mode="json", exclude_unset=True)
        elif isinstance(codereview_raw, dict):
            codereview = dict(codereview_raw)
        legacy_codereview_keys = (
            "codereview",
            "codereview_snippet",
            "codereview_language",
            "codereview_phase",
            "codereview_selections",
            "codereview_confirmed",
        )
        if "codereview_snippet" in data:
            codereview.setdefault("snippet", data["codereview_snippet"])
        if "codereview_language" in data:
            codereview.setdefault("language", data["codereview_language"])
        if "codereview_phase" in data:
            codereview.setdefault("phase", data["codereview_phase"])
        if "codereview_selections" in data:
            codereview.setdefault("selections", data["codereview_selections"])
        if "codereview_confirmed" in data:
            codereview.setdefault("confirmed", data["codereview_confirmed"])
        if any(key in data for key in legacy_codereview_keys):
            data["codereview"] = codereview

        debate_raw = data.get("debate")
        debate: dict[str, Any] = {}
        if isinstance(debate_raw, PersistedDebateState):
            debate = debate_raw.model_dump(mode="json", exclude_unset=True)
        elif isinstance(debate_raw, dict):
            debate = dict(debate_raw)
        legacy_debate_keys = (
            "debate",
            "debate_statement",
            "debate_phase",
            "debate_sides",
            "debate_arguments",
            "debate_champions",
            "debate_auto_assigned",
            "debate_first_side",
            "debate_round_index",
            "debate_round_timer_seconds",
            "debate_round_timer_started_at",
        )
        if "debate_statement" in data:
            debate.setdefault("statement", data["debate_statement"])
        if "debate_phase" in data:
            debate.setdefault("phase", data["debate_phase"])
        if "debate_sides" in data:
            debate.setdefault("sides", data["debate_sides"])
        if "debate_arguments" in data:
            debate.setdefault("arguments", data["debate_arguments"])
        if "debate_champions" in data:
            debate.setdefault("champions", data["debate_champions"])
        if "debate_auto_assigned" in data:
            debate.setdefault("auto_assigned", data["debate_auto_assigned"])
        if "debate_first_side" in data:
            debate.setdefault("first_side", data["debate_first_side"])
        if "debate_round_index" in data:
            debate.setdefault("round_index", data["debate_round_index"])
        if "debate_round_timer_seconds" in data:
            debate.setdefault("round_timer_seconds", data["debate_round_timer_seconds"])
        if "debate_round_timer_started_at" in data:
            debate.setdefault("round_timer_started_at", data["debate_round_timer_started_at"])
        if any(key in data for key in legacy_debate_keys):
            data["debate"] = debate

        return data

    @field_validator("poll_correct_ids", mode="before")
    @classmethod
    def _normalize_poll_correct_ids(_cls, value):
        return [] if value is None else value
