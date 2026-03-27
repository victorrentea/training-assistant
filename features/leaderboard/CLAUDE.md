# Leaderboard

## Purpose
Kahoot-style dramatic leaderboard reveal triggered by host. Reveals top-5 positions sequentially from 5th to 1st. Participants see their own rank on their phone. Scores can also be reset from this feature.

## Endpoints
- `POST /api/leaderboard/show` — activate leaderboard overlay; broadcasts top-5 reveal sequence to all
- `POST /api/leaderboard/hide` — hide leaderboard; broadcasts `leaderboard_hide` to all
- `DELETE /api/scores` — reset all participant scores and base_scores to zero

## WebSocket Messages
- `leaderboard_hide` (server → all) — sent when host hides the leaderboard

## State Fields
Fields in `AppState` owned by this feature:
- `leaderboard_active: bool` — whether the leaderboard overlay is currently visible
- `scores: dict[str, int]` — uuid → total score (shared with poll, Q&A, codereview, debate)
- `base_scores: dict[str, int]` — uuid → score at last poll open (for speed delta calculation)

## Design Decisions
- `broadcast_leaderboard()` in `core/messaging.py` handles the personalized leaderboard broadcast: each participant receives their own rank and score in addition to the top-5 list.
- The leaderboard reveal sends a single payload with the ordered top-5 list; the client animates the sequential reveal.
- Scores are shared state owned logically across features (poll awards speed points, Q&A awards submission/upvote points, debate awards argument/champion points, codereview awards confirmed-line points).
- `DELETE /api/scores` is in this router for convenience since it's conceptually tied to the leaderboard reset workflow.
