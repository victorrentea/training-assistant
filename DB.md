# DB Reference (Generated from Persisted Models)

Generated from `daemon/persisted_models.py`.

## Table of Contents
- [Global State](#global-state)
- [Session State](#session-state)

## Global State
### `PersistedGlobalState`

```
active_session_id?: string
active_since?: string
log_level?: string
```

## Session State
### `PersistedSessionState`

```
session_id?: string  # URL-safe alphanumeric join code (CSPRNG-generated)
saved_at?: string  # ISO timestamp of last snapshot write
mode?: string  # workshop | talk
current_activity?: string  # none | quiz | wordcloud | qa | codereview | debate
participants?: dict[str, PersistedParticipant{
  name?:string
  avatar?:string
  score?:int | number
  location?:string
  engagement?:dict[str, ViewEngagement{
    seconds?:int
    visits?:int
    clicks?:int
  }]
}]  # participant_uuid → identity/score
quiz?: PersistedQuizState{
  definition?:dict[str, any]  # Quiz question and options as shown to participants
  active?:bool
  correct_indices?:list[int]  # Option indices marked as correct answers
  opened_at?:string
  end_timer_seconds?:int
  end_timer_started_at?:string
  votes?:dict[str, any]  # participant_uuid → chosen option ID(s)
  awarded_points?:dict[str, int]  # participant_uuid → points awarded by most recent reveal_correct
}
poll?: PersistedPollState{
  data?:dict[str, any]
  started?:bool
  opened_at?:string
  votes?:dict[str, any]
}
qa?: dict[str, any]
qa_questions?: dict[str, dict[str, any]]  # question_id → {text, author, upvoters, answered}
wordcloud?: PersistedWordCloudState{
  words?:dict[str, int]  # word → submission count
  word_order?:list[string]  # Words in submission order
  topic?:string
}
codereview?: PersistedCodeReviewState{
  snippet?:string
  language?:string
  phase?:string  # reviewing | revealed
  selections?:dict[str, list[int]]  # participant_uuid → selected line indices
  confirmed?:list[int]  # Host-confirmed bug line indices
}
debate?: PersistedDebateState{
  statement?:string
  phase?:string  # side_selection | arguments | ai_cleanup | prep | live_debate | ended
  sides?:dict[str, string]  # participant_uuid → for | against
  arguments?:list[dict[str, any]]  # Submitted arguments [{participant_uuid, side, text}]
  champions?:dict[str, string]  # side → champion participant_uuid
  auto_assigned?:list[string]  # UUIDs auto-assigned to a side
  first_side?:string  # Which side speaks first in live debate
  round_index?:int
  round_timer_seconds?:int
  round_timer_started_at?:string
}
talk_presentation_name?: string  # Display name of the last PPTX dropped in talk mode (stem, no extension)
talk_presentation_url?: string  # PDF export URL for talk PPTX (docs.google.com/presentation/d/.../export/pdf)
talk_presentation_slug?: string  # Railway slug under which the talk PPTX PDF is cached
fx_enabled?: bool  # Master switch for the FX button; armed by default each session
fx_granted_pids?: list[string]  # Participant UUIDs the host has granted the FX button to
fx_press_counts?: dict[str, int]  # Per-participant count of successful FX presses this session
fx_tile_n?: int  # Soundboard tile the FX button fires
fx_cooldown_seconds?: int  # Minimum seconds between two FX triggers
fx_last_fired_at?: number  # Epoch seconds of the last FX trigger (host tooltip only)
current_slide?: dict[str, any]  # {slug, page}
slides_viewed?: list[ViewedSlide{
  slug:string  # Railway slug identifying the slide deck
  page:int  # 1-based slide number
  seconds?:int  # Cumulative seconds viewed
}]  # Accumulated per-slide viewing durations from addons
slide_timeline?: list[SlideMoment{
  slug:string  # Railway slug identifying the slide deck
  page:int  # 1-based slide number
  seconds?:int  # Focused seconds within this window
  at:string  # ISO timestamp of the end of the window
}]  # Append-only log of when each slide held the screen, for tying summary sections to slide numbers
emoji_counters?: dict[str, int]  # emoji → cumulative reaction count (talk mode)
```

### `PersistedSessionMeta`

```
session_id?: string
session_type?: string
```
