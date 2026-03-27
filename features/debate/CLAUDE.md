# Debate

## Purpose
Structured in-room debate activity with side selection, argument submission, AI-powered argument cleanup, champion volunteering, and a timed live debate phase with 4 rounds.

## Endpoints
- `POST /api/debate` — launch a debate with a statement; resets all debate state
- `POST /api/debate/reset` — reset debate to scratch (NONE activity)
- `POST /api/debate/close-selection` — close side selection; auto-assign unassigned participants to balance teams
- `POST /api/debate/force-assign` — force-assign all remaining unassigned participants
- `POST /api/debate/phase` — advance to a specific phase (`arguments|ai_cleanup|prep|live_debate|ended`)
- `POST /api/debate/first-side` — pick which side speaks first in live debate
- `POST /api/debate/round-timer` — start a timed round (index + seconds); broadcast `debate_timer`
- `POST /api/debate/end-round` — end current round early; broadcast `debate_round_ended`
- `POST /api/debate/end-arguments` — end arguments phase; queue AI cleanup payload for daemon
- `GET /api/debate/ai-request` — daemon polls for pending AI cleanup payload (clears on read)
- `POST /api/debate/ai-result` — daemon posts AI cleanup results; apply merges + new args; advance to prep

## WebSocket Messages
- `debate_pick_side` → participant picks "for" or "against"; triggers auto-assign if ≥50% have picked
- `debate_argument` → participant submits argument text (max 280 chars, must be in `arguments` phase); awards 100 pts
- `debate_upvote` → upvote an argument (not own); 50 pts to author, 25 pts to voter
- `debate_volunteer` → volunteer as champion for your side (prep phase only); awards 2500 pts
- `debate_timer` (server → all) → round timer started
- `debate_round_ended` (server → all) → round ended early

## State Fields
Fields in `AppState` owned by this feature:
- `debate_statement: str | None`
- `debate_phase: str | None` — `"side_selection"|"arguments"|"ai_cleanup"|"prep"|"live_debate"|"ended"`
- `debate_sides: dict[str, str]` — uuid → `"for"` | `"against"`
- `debate_arguments: list[dict]` — `{id, author_uuid, side, text, upvoters: set, ai_generated, merged_into}`
- `debate_champions: dict[str, str]` — `"for"|"against"` → uuid of volunteer champion
- `debate_auto_assigned: set[str]` — uuids that were auto-assigned (not self-selected)
- `debate_first_side: str | None` — which side speaks first in live debate
- `debate_round_index: int | None` — current round index (0–3)
- `debate_round_timer_seconds: int | None`
- `debate_round_timer_started_at: datetime | None`
- `debate_ai_request: dict | None` — pending payload for daemon AI cleanup

## Design Decisions
- Auto-assign triggers when ≥50% of participants have picked a side.
- Live debate has 4 rounds: opening FOR, opening AGAINST, rebuttal FOR, rebuttal AGAINST.
- AI cleanup merges duplicate arguments, fixes typos, and can suggest new AI-generated ones.
- Late joiners (after `side_selection`) are auto-assigned to the smaller side.
- `upvoters` and `debate_auto_assigned` are Python `set`; serialized to lists for JSON.
