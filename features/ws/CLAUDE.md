# WebSocket (ws)

## Purpose
Single WebSocket endpoint that handles all real-time participant, host, overlay, and daemon connections. Dispatches all incoming messages to the appropriate feature logic and sends personalized state on connect.

## Endpoints (WebSocket)
- `WS /ws/{participant_id}` — participant (`uuid`), host (`__host__`), or overlay (`__overlay__`) connection
- `WS /ws/daemon` — daemon connection (heartbeat + slide upload result handling)

## WebSocket Messages Dispatched
Inbound participant messages handled here:
- `set_name` → register/rename participant; auto-assign debate side if late joiner
- `refresh_avatar` → re-roll avatar (conference mode)
- `location` → store participant city/timezone
- `vote` / `multi_vote` → single/multi-option poll vote
- `wordcloud_word` → submit word to word cloud
- `qa_submit` / `qa_upvote` → Q&A submission and upvoting
- `debate_pick_side` / `debate_argument` / `debate_upvote` / `debate_volunteer` → debate interactions
- `codereview_select` / `codereview_deselect` → flag/unflag code review lines
- `emoji_reaction` → forward emoji to overlay and host

Inbound daemon messages:
- `slides_upload_result` → notify waiting slide-fetch requests of upload completion
- `daemon_ping` → heartbeat (updates `daemon_last_seen`)

## State Fields
Fields in `AppState` owned by this feature:
- `participants: dict[str, WebSocket]` — uuid → active WS connection
- `participant_history: set[str]` — all UUIDs ever seen (persists across disconnects)
- `participant_ips: dict[str, str]` — uuid → client IP address
- `daemon_ws: WebSocket | None` — active daemon WS connection

## Design Decisions
- First message from a new participant must be `set_name`; others are dropped until named.
- Conference mode auto-names participants immediately (no set_name required); name is set to `""` initially.
- Host and overlay are always "named" on connect; host receives full state immediately via `send_state_to_host()`.
- On reconnect, old host/overlay connections are kicked (`close 1001`) before accepting the new one.
- Participant names and scores persist across WebSocket disconnects (stored in `participant_names`, `scores`).
- `paused_participant_uuids` check: participants from a paused session receive `session_paused` and are disconnected.
- Auth for host/daemon WS connections uses HTTP Basic Auth header (same credentials as REST endpoints).
