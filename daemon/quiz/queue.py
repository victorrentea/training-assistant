"""In-memory poll queue — stores pre-submitted questions for one-at-a-time firing."""


class PollQueue:
    def __init__(self):
        self._questions: list[dict] = []

    def submit(self, questions: list[dict]) -> None:
        """Replace the entire queue."""
        self._questions = list(questions)

    def current(self) -> dict | None:
        """Return the first question in the queue, or None if empty."""
        return self._questions[0] if self._questions else None

    def all_items(self) -> list[dict]:
        """Return all queued questions."""
        return list(self._questions)

    def pending_count(self) -> int:
        """Return the number of questions remaining."""
        return len(self._questions)

    def remove(self, index: int) -> None:
        """Remove the question at the given 0-based index."""
        del self._questions[index]

    def clear(self) -> None:
        """Discard all questions."""
        self._questions = []


quiz_queue = PollQueue()
