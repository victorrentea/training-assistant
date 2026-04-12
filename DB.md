# DB Reference (Generated from Persisted Models)

Generated from `daemon/persisted_models.py`.

## Table of Contents
- [Global State](#global-state)
- [Session State](#session-state)

## Global State
### `PersistedGlobalState`

```
active_session_id?: string
session_id?: string
log_level?: string
main?: PersistedSessionRef {
    name?:string
    started_at?:string
    status?:string
    ended_at?:string
    paused_intervals?:list[dict[str, any]]
}
talk?: PersistedSessionRef {
    name?:string
    started_at?:string
    status?:string
    ended_at?:string
    paused_intervals?:list[dict[str, any]]
}
stack?: list[PersistedSessionRef {
    name?:string
    started_at?:string
    status?:string
    ended_at?:string
    paused_intervals?:list[dict[str, any]]
}]
```

## Session State
### `PersistedSessionState`

```
session_id?: string
session_name?: string
saved_at?: string
mode?: string
activity?: string
current_activity?: string
participants?: dict[str, PersistedParticipant {
    name?:string
    avatar?:string
    score?:int | number
    location?:string
}]
poll?: PersistedPollState {
    definition?:dict[str, any]
    active?:bool
    correct_ids?:list[string]
    opened_at?:string
    timer_seconds?:int
    timer_started_at?:string
    votes?:dict[str, any]
}
qa?: dict[str, any]
qa_questions?: dict[str, dict[str, any]]
wordcloud?: PersistedWordCloudState {
    words?:dict[str, int]
    word_order?:list[string]
    topic?:string
}
codereview?: PersistedCodeReviewState {
    snippet?:string
    language?:string
    phase?:string
    selections?:dict[str, list[int]]
    confirmed?:list[int]
}
debate?: PersistedDebateState {
    statement?:string
    phase?:string
    sides?:dict[str, string]
    arguments?:list[dict[str, any]]
    champions?:dict[str, string]
    auto_assigned?:list[string]
    first_side?:string
    round_index?:int
    round_timer_seconds?:int
    round_timer_started_at?:string
}
slides_current?: dict[str, any]
token_usage?: dict[str, any]
```

### `PersistedSessionMeta`

```
session_id?: string
started_at?: string
paused_intervals?: list[dict[str, any]]
talk?: PersistedSessionRef {
    name?:string
    started_at?:string
    status?:string
    ended_at?:string
    paused_intervals?:list[dict[str, any]]
}
```
