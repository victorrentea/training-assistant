# DB Reference (Generated from Persisted Models)

Generated from `daemon/persisted_models.py`.

## Table of Contents
- [Global State](#global-state)
- [Session State](#session-state)

## Global State
| Structure | Shape |
| --- | --- |
| `PersistedGlobalState` | `active_session_id?: string`<br>`session_id?: string`<br>`log_level?: string`<br>`main?: PersistedSessionRef {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`name?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`started_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`status?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`ended_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`paused_intervals?:list[dict[str, any]]`<br>`}`<br>`talk?: PersistedSessionRef {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`name?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`started_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`status?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`ended_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`paused_intervals?:list[dict[str, any]]`<br>`}`<br>`stack?: list[PersistedSessionRef {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`name?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`started_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`status?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`ended_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`paused_intervals?:list[dict[str, any]]`<br>`}]` |

## Session State
| Structure | Shape |
| --- | --- |
| `PersistedSessionState` | `session_id?: string`<br>`session_name?: string`<br>`saved_at?: string`<br>`mode?: string`<br>`activity?: string`<br>`current_activity?: string`<br>`participants?: dict[str, dict[str, any]]`<br>`participant_names?: dict[str, string]`<br>`participant_avatars?: dict[str, string]`<br>`participant_universes?: dict[str, string]`<br>`scores?: dict[str, int \| number]`<br>`locations?: dict[str, string]`<br>`poll?: dict[str, any]`<br>`poll_active?: bool`<br>`poll_correct_ids?: list[string]`<br>`poll_opened_at?: string`<br>`poll_timer_seconds?: int`<br>`poll_timer_started_at?: string`<br>`votes?: dict[str, any]`<br>`qa?: dict[str, any]`<br>`qa_questions?: dict[str, dict[str, any]]`<br>`wordcloud?: dict[str, any]`<br>`wordcloud_words?: dict[str, int]`<br>`wordcloud_word_order?: list[string]`<br>`wordcloud_topic?: string`<br>`codereview?: dict[str, any]`<br>`codereview_snippet?: string`<br>`codereview_language?: string`<br>`codereview_phase?: string`<br>`codereview_selections?: dict[str, list[int]]`<br>`codereview_confirmed?: list[int]`<br>`debate?: dict[str, any]`<br>`debate_statement?: string`<br>`debate_phase?: string`<br>`debate_sides?: dict[str, string]`<br>`debate_arguments?: list[dict[str, any]]`<br>`debate_champions?: dict[str, string]`<br>`debate_auto_assigned?: list[string]`<br>`debate_first_side?: string`<br>`debate_round_index?: int`<br>`debate_round_timer_seconds?: int`<br>`debate_round_timer_started_at?: string`<br>`slides_current?: dict[str, any]`<br>`summary_points?: list[dict[str, any]]`<br>`leaderboard_active?: bool`<br>`token_usage?: dict[str, any]` |
| `PersistedSessionMeta` | `session_id?: string`<br>`started_at?: string`<br>`paused_intervals?: list[dict[str, any]]`<br>`talk?: PersistedSessionRef {`<br>&nbsp;&nbsp;&nbsp;&nbsp;`name?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`started_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`status?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`ended_at?:string`<br>&nbsp;&nbsp;&nbsp;&nbsp;`paused_intervals?:list[dict[str, any]]`<br>`}` |
