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
            if "wordcloud_words" in data:
                self.words.clear()
                self.words.update(data["wordcloud_words"])
            if "wordcloud_word_order" in data:
                self.word_order.clear()
                self.word_order.extend(data["wordcloud_word_order"])
            if "wordcloud_topic" in data:
                self.topic = data["wordcloud_topic"]

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
