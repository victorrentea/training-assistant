# Q&A

## Purpose
Allows the host to moderate participant-submitted questions: edit text, delete, and mark as answered. Q&A submission and upvoting happen via WebSocket (no REST endpoints for those).

## Endpoints
- `PUT /api/qa/question/{id}/text` — edit question text (host only, max 280 chars)
- `DELETE /api/qa/question/{id}` — delete a question
- `PUT /api/qa/question/{id}/answered` — toggle answered flag on a question
- `POST /api/qa/clear` — delete all questions

## WebSocket Messages
- `qa_submit` (participant → server) → submit a new question; awards 100 points to submitter
- `qa_upvote` (participant → server) → upvote a question (not own); awards 50 pts to author, 25 pts to voter

## State Fields
Fields in `AppState` owned by this feature:
- `qa_questions: dict[str, dict]` — qid → `{id, text, author, upvoters: set, answered, timestamp}`

## Design Decisions
- Q&A submit and upvote go through WebSocket only — no REST endpoints for participants.
- Max question length is 280 characters (Twitter-style limit).
- `upvoters` is a Python `set` in memory; serialized to list for JSON.
- Participants cannot upvote their own question (`q["author"] != pid` check in ws router).
- Host can edit submitted questions (e.g. fix typos, merge semantically equivalent ones).
- Questions are sorted by upvote count on the client side.
