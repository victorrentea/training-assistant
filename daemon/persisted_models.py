"""Pydantic models for JSON payloads persisted by the daemon."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PersistedModel(BaseModel):
    """Base persisted model: tolerate forward/backward-compatible extra fields."""

    model_config = ConfigDict(extra="allow")


class PersistedGlobalState(PersistedModel):
    """Global daemon state persisted in `global-state.json`."""

    active_session_id: str | None = None
    log_level: str | None = None


class PersistedSessionMeta(PersistedModel):
    """Read-only projection: extracts session identity from `session-state.json`."""

    session_id: str | None = None
    session_type: str | None = None


class PersistedParticipant(PersistedModel):
    """Participant identity persisted in session snapshots."""

    name: str | None = None
    avatar: str | None = None
    score: int | float | None = None
    location: str | None = None


class PersistedPollState(PersistedModel):
    """Poll snapshot persisted in session state."""

    definition: dict[str, Any] | None = Field(default=None, description="Poll question and options as shown to participants")
    active: bool | None = None
    correct_indices: list[int] = Field(default_factory=list, description="Option indices marked as correct answers")
    opened_at: str | None = None
    end_timer_seconds: int | None = None
    end_timer_started_at: str | None = None
    votes: dict[str, Any] = Field(default_factory=dict, description="participant_uuid → chosen option ID(s)")
    awarded_points: dict[str, int] = Field(default_factory=dict, description="participant_uuid → points awarded by most recent reveal_correct")


class PersistedWordCloudState(PersistedModel):
    """Word cloud snapshot persisted in session state."""

    words: dict[str, int] = Field(default_factory=dict, description="word → submission count")
    word_order: list[str] = Field(default_factory=list, description="Words in submission order")
    topic: str | None = None


class PersistedCodeReviewState(PersistedModel):
    """Code review snapshot persisted in session state."""

    snippet: str | None = None
    language: str | None = None
    phase: str | None = Field(default=None, description="reviewing | revealed")
    selections: dict[str, list[int]] = Field(default_factory=dict, description="participant_uuid → selected line indices")
    confirmed: list[int] = Field(default_factory=list, description="Host-confirmed bug line indices")


class PersistedDebateState(PersistedModel):
    """Debate snapshot persisted in session state."""

    statement: str | None = None
    phase: str | None = Field(default=None, description="side_selection | arguments | ai_cleanup | prep | live_debate | ended")
    sides: dict[str, str] = Field(default_factory=dict, description="participant_uuid → for | against")
    arguments: list[dict[str, Any]] = Field(default_factory=list, description="Submitted arguments [{participant_uuid, side, text}]")
    champions: dict[str, str] = Field(default_factory=dict, description="side → champion participant_uuid")
    auto_assigned: list[str] = Field(default_factory=list, description="UUIDs auto-assigned to a side")
    first_side: str | None = Field(default=None, description="Which side speaks first in live debate")
    round_index: int | None = None
    round_timer_seconds: int | None = None
    round_timer_started_at: str | None = None


class ViewedSlide(PersistedModel):
    """Single slide viewing record: cumulative seconds on one (slug, page) pair."""

    slug: str = Field(description="Railway slug identifying the slide deck")
    page: int = Field(description="1-based slide number")
    seconds: int = Field(default=0, description="Cumulative seconds viewed")


class PersistedGitRepoActivity(PersistedModel):
    """Single git repo+branch entry with accumulated file paths."""
    url: str = ""
    branch: str = ""
    files: list[str] = Field(default_factory=list, description="File paths opened in this repo+branch")


class PersistedSessionState(PersistedModel):
    """Runtime session snapshot persisted in `session-state.json`."""

    session_id: str | None = Field(default=None, description="6-char alphanumeric join code")
    saved_at: str | None = Field(default=None, description="ISO timestamp of last snapshot write")
    mode: str | None = Field(default=None, description="workshop | talk")
    current_activity: str | None = Field(default=None, description="none | poll | wordcloud | qa | codereview | debate")

    participants: dict[str, PersistedParticipant] = Field(default_factory=dict, description="participant_uuid → identity/score")
    # Legacy split maps: accepted on read, omitted on write.
    participant_names: dict[str, str] = Field(default_factory=dict, exclude=True)
    participant_avatars: dict[str, str] = Field(default_factory=dict, exclude=True)
    participant_universes: dict[str, str] = Field(default_factory=dict, exclude=True)
    scores: dict[str, int | float] = Field(default_factory=dict, exclude=True)
    locations: dict[str, str] = Field(default_factory=dict, exclude=True)

    poll: PersistedPollState | None = None
    # Legacy flat poll fields: accepted on read, omitted on write.
    poll_active: bool | None = Field(default=None, exclude=True)
    poll_correct_indices: list[int] = Field(default_factory=list, exclude=True)
    poll_opened_at: str | None = Field(default=None, exclude=True)
    poll_timer_seconds: int | None = Field(default=None, exclude=True)
    poll_timer_started_at: str | None = Field(default=None, exclude=True)
    votes: dict[str, Any] = Field(default_factory=dict, exclude=True)

    qa: dict[str, Any] | None = None
    qa_questions: dict[str, dict[str, Any]] = Field(default_factory=dict, description="question_id → {text, author, upvoters, answered}")

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

    gdrive_url: str | None = Field(default=None, description="Google Drive web URL for the session folder (resolved at session create time)")
    talk_presentation_name: str | None = Field(default=None, description="Display name of the last PPTX dropped in talk mode (stem, no extension)")
    talk_presentation_url: str | None = Field(default=None, description="PDF export URL for talk PPTX (docs.google.com/presentation/d/.../export/pdf)")
    talk_presentation_slug: str | None = Field(default=None, description="Railway slug under which the talk PPTX PDF is cached")
    current_slide: dict[str, Any] | None = Field(default=None, description="{slug, page}")
    slides_viewed: list[ViewedSlide] = Field(default_factory=list, description="Accumulated per-slide viewing durations from addons")
    git_repos: list[PersistedGitRepoActivity] = Field(default_factory=list, description="Accumulated git file-open events for this session")
    emoji_counters: dict[str, int] = Field(default_factory=dict, description="emoji → cumulative reaction count (talk mode)")

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_participant_maps(_cls, value):
        if not isinstance(value, dict):
            return value

        data = dict(value)
        data.pop("summary_points", None)
        data.pop("leaderboard_active", None)

        participants_raw = data.get("participants")
        participants: dict[str, dict[str, Any]] = {}
        if isinstance(participants_raw, dict):
            for pid, entry in participants_raw.items():
                pid_str = str(pid)
                if isinstance(entry, PersistedParticipant):
                    participants[pid_str] = entry.model_dump(mode="json", exclude_unset=True)
                elif isinstance(entry, dict):
                    participants[pid_str] = dict(entry)

        _names_raw = data.get("participant_names")
        names: dict = _names_raw if isinstance(_names_raw, dict) else {}
        _avatars_raw = data.get("participant_avatars")
        avatars: dict = _avatars_raw if isinstance(_avatars_raw, dict) else {}
        _scores_raw = data.get("scores")
        scores: dict = _scores_raw if isinstance(_scores_raw, dict) else {}
        _locations_raw = data.get("locations")
        locations: dict = _locations_raw if isinstance(_locations_raw, dict) else {}

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
                "correct_indices",
                "opened_at",
                "end_timer_seconds",
                "end_timer_started_at",
                "votes",
            }
            if not any(key in poll for key in poll_keys):
                poll = {"definition": dict(poll_raw)}
        legacy_poll_keys = (
            "poll",
            "poll_active",
            "poll_correct_indices",
            "poll_opened_at",
            "poll_timer_seconds",
            "poll_timer_started_at",
            "votes",
        )
        if "poll_active" in data:
            poll.setdefault("active", data["poll_active"])
        if "poll_correct_indices" in data:
            legacy_correct_indices = data["poll_correct_indices"]
            data["poll_correct_indices"] = [] if legacy_correct_indices is None else legacy_correct_indices
            poll.setdefault("correct_indices", data["poll_correct_indices"])
        if "poll_opened_at" in data:
            poll.setdefault("opened_at", data["poll_opened_at"])
        if "poll_timer_seconds" in data:
            poll.setdefault("end_timer_seconds", data["poll_timer_seconds"])
        if "poll_timer_started_at" in data:
            poll.setdefault("end_timer_started_at", data["poll_timer_started_at"])
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

