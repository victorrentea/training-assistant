"""Unit tests for PollQueue."""
import pytest
from daemon.quiz.queue import PollQueue

Q1 = {"question": "Q1", "options": ["a", "b"], "correct_indices": [0]}
Q2 = {"question": "Q2", "options": ["c", "d"], "correct_indices": [1]}
Q3 = {"question": "Q3", "options": ["e", "f"], "correct_indices": [0]}


class TestPollQueueRemove:
    def test_remove_first_item_leaves_second_as_current(self):
        q = PollQueue()
        q.submit([Q1, Q2])
        q.remove(0)
        assert q.pending_count() == 1
        assert q.current()["question"] == "Q2"

    def test_remove_middle_item(self):
        q = PollQueue()
        q.submit([Q1, Q2, Q3])
        q.remove(1)
        assert q.pending_count() == 2
        assert q.all_items()[0]["question"] == "Q1"
        assert q.all_items()[1]["question"] == "Q3"

    def test_remove_last_item_leaves_empty(self):
        q = PollQueue()
        q.submit([Q1])
        q.remove(0)
        assert q.pending_count() == 0
        assert q.current() is None

    def test_remove_invalid_index_raises(self):
        q = PollQueue()
        q.submit([Q1])
        with pytest.raises(IndexError):
            q.remove(5)

    def test_current_returns_first_item(self):
        q = PollQueue()
        q.submit([Q1, Q2])
        assert q.current()["question"] == "Q1"

    def test_all_items_returns_full_list(self):
        q = PollQueue()
        q.submit([Q1, Q2, Q3])
        items = q.all_items()
        assert len(items) == 3
        assert items[1]["question"] == "Q2"

    def test_pending_count_equals_length(self):
        q = PollQueue()
        q.submit([Q1, Q2, Q3])
        assert q.pending_count() == 3
        q.remove(0)
        assert q.pending_count() == 2
