# Daemon Persisted State

## Disk location

- `sessions_root` = `SESSIONS_FOLDER` env var, default: `~/My Drive/Cursuri/###sesiuni`
- Global daemon state file: `${sessions_root}/training-assistant-global-state.json`
- Per-session state file: `${sessions_root}/${session_name}/session_state.json`

## What is stored

- Global (`training-assistant-global-state.json`):
  - `main`: active/paused/ended workshop session metadata
  - `talk`: active/paused/ended nested talk session metadata (or `null`)
  - `session_id`: currently active public session id (stable join id)
- Per-session (`session_state.json`):
  - Full serialized session snapshot from backend (`/api/session/snapshot`), including `session_id`, participants, activity, poll/qa/wordcloud/debate/codereview, leaderboard flag, token usage, slides/git logs.

## Class diagram

```mermaid
classDiagram
    class SessionsRoot {
      +path: SESSIONS_FOLDER
    }

    class DaemonStateFile {
      +path: training-assistant-global-state.json
      +main: SessionRef?
      +talk: SessionRef?
      +session_id: string?
    }

    class SessionRef {
      +name: string
      +started_at: iso-datetime
      +ended_at: iso-datetime?
      +status: active|paused|ended
      +paused_intervals: PauseInterval[]
    }

    class PauseInterval {
      +from: iso-datetime
      +to: iso-datetime?
      +reason: explicit|nested|day_end
    }

    class SessionFolder {
      +name: string
      +path: /sessions_root/{name}
    }

    class SessionStateFile {
      +path: session_state.json
      +saved_at: iso-datetime
      +session_id: string
      +mode: workshop|conference
      +participants: map
      +activity: none|poll|wordcloud|qa|debate|codereview
      +poll: object?
      +qa: object
      +wordcloud: object
      +debate: object
      +codereview: object
      +leaderboard_active: bool
      +token_usage: object
      +slides_log: list
      +git_repos: list
    }

    SessionsRoot "1" o-- "1" DaemonStateFile : stores global
    SessionsRoot "1" o-- "*" SessionFolder : contains
    SessionFolder "1" o-- "1" SessionStateFile : stores per-session
    DaemonStateFile "1" --> "0..1" SessionRef : main
    DaemonStateFile "1" --> "0..1" SessionRef : talk
    SessionRef "1" o-- "*" PauseInterval
```
