"""In-memory poll queue — stores pre-submitted questions for one-at-a-time firing."""


class PollQueue:
    def __init__(self):
        self._questions: list[dict] = []
        self._index: int = 0

    def submit(self, questions: list[dict]) -> None:
        """Replace the entire queue and reset the index."""
        self._questions = list(questions)
        self._index = 0

    def current(self) -> dict | None:
        """Return the next question to be fired, or None if the queue is exhausted."""
        if self._index < len(self._questions):
            return self._questions[self._index]
        return None

    def pending_count(self) -> int:
        """Return the number of questions remaining (including the current one)."""
        return max(0, len(self._questions) - self._index)

    def advance(self) -> None:
        """Move to the next question."""
        self._index += 1

    def clear(self) -> None:
        """Discard all questions."""
        self._questions = []
        self._index = 0


quiz_queue = PollQueue()
