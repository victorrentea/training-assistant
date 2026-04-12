# DB Reference (Generated from Persisted Models)

Generated from `daemon/persisted_models.py`.

## Table of Contents
- [Global State](#global-state)
- [Session State](#session-state)

## Global State
### `PersistedGlobalState`

```
active_session_id?: string
log_level?: string
```

## Session State
### `PersistedSessionState`

```
session_id?: string  # 6-char alphanumeric join code
saved_at?: string  # ISO timestamp of last snapshot write
mode?: string  # workshop | conference
activity?: string
current_activity?: string
participants?: dict[str, PersistedParticipant {
  name?:string
  avatar?:string
  score?:int | number
  location?:string
}]  # participant_uuid → identity/score
poll?: PersistedPollState {
  definition?:dict[str, any]  # Poll question and options as shown to participants
  active?:bool
  correct_ids?:list[string]  # Option IDs marked as correct answers
  opened_at?:string
  timer_seconds?:int
  timer_started_at?:string
  votes?:dict[str, any]  # participant_uuid → chosen option ID(s)
}
qa?: dict[str, any]
qa_questions?: dict[str, dict[str, any]]  # question_id → {text, author, upvoters, answered}
wordcloud?: PersistedWordCloudState {
  words?:dict[str, int]  # word → submission count
  word_order?:list[string]  # Words in submission order
  topic?:string
}
codereview?: PersistedCodeReviewState {
  snippet?:string
  language?:string
  phase?:string  # reviewing | revealed
  selections?:dict[str, list[int]]  # participant_uuid → selected line indices
  confirmed?:list[int]  # Host-confirmed bug line indices
}
debate?: PersistedDebateState {
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
slides_current?: dict[str, any]  # {presentation_name, current_page}
```

### `PersistedSessionMeta`

```
session_id?: string
```
