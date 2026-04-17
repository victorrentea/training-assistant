"""Word cloud state cache for daemon.

Owns the word cloud state (words, word_order, topic).
Initial data comes from daemon_state_push on WS connect.
"""
import threading


class WordCloudState:
    """Word cloud state. Mutation methods run on uvicorn's single-threaded
    event loop (no lock needed). sync_from_restore runs on the main thread
    and uses _lock for cross-thread safety.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.words: dict[str, int] = {}
        self.word_order: list[str] = []  # newest first
        self.topic: str = ""

    def sync_from_restore(self, data: dict):
        """Update from daemon_state_push. Called from main thread."""
        with self._lock:
            payload = data.get("wordcloud")
            if not isinstance(payload, dict):
                payload = {}

            has_words = "words" in payload or "wordcloud_words" in data
            words = payload.get("words") if "words" in payload else data.get("wordcloud_words")
            if has_words:
                self.words.clear()
                self.words.update(words or {})

            has_word_order = "word_order" in payload or "wordcloud_word_order" in data
            word_order = payload.get("word_order") if "word_order" in payload else data.get("wordcloud_word_order")
            if has_word_order:
                self.word_order.clear()
                self.word_order.extend(word_order or [])

            has_topic = "topic" in payload or "wordcloud_topic" in data
            topic = payload.get("topic") if "topic" in payload else data.get("wordcloud_topic")
            if has_topic:
                self.topic = topic or ""

    def add_word(self, word: str) -> dict:
        """Add a word, return current state for broadcast."""
        word = word.strip().lower()
        if word not in self.words:
            self.word_order.insert(0, word)
        self.words[word] = self.words.get(word, 0) + 1
        return self.snapshot()

    def set_topic(self, topic: str) -> dict:
        """Set topic, return current state for broadcast."""
        self.topic = topic.strip()
        return self.snapshot()

    def clear(self) -> dict:
        """Clear all words and topic, return empty state for broadcast."""
        self.words.clear()
        self.word_order.clear()
        self.topic = ""
        return self.snapshot()

    def snapshot(self) -> dict:
        """Return a copy of current state."""
        return {
            "words": dict(self.words),
            "word_order": list(self.word_order),
            "topic": self.topic,
        }


# Module-level singleton
wordcloud_state = WordCloudState()
