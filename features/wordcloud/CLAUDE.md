# Word Cloud

## Purpose
Lets participants submit words that aggregate into an animated live word cloud. The host sets a topic prompt; participants submit words via WebSocket; the cloud updates in real time for everyone.

## Endpoints
- `POST /api/wordcloud/topic` — set the topic prompt displayed to participants
- `POST /api/wordcloud/clear` — clear all words and reset topic

## WebSocket Messages
- `wordcloud_word` (participant → server) → submit a word; awards 200 points to submitter; increments word count; tracks submission order for animated reveal

## State Fields
Fields in `AppState` owned by this feature:
- `wordcloud_words: dict[str, int]` — word → count
- `wordcloud_word_order: list[str]` — insertion order (newest first, for animation)
- `wordcloud_topic: str` — topic prompt shown to participants

## Design Decisions
- Words are lowercased before storage; word order tracks first submission time (newest-first).
- Each word submission awards 200 points regardless of repetition.
- Host must set `current_activity = WORDCLOUD` via the activity endpoint before the word cloud is shown to participants.
- `wordcloud_word_order` is a list (not a set) to preserve submission order for animated cloud rendering.
