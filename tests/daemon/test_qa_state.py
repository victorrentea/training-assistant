"""Tests for daemon Q&A state."""
import pytest
from daemon.qa.state import QAState


class TestQAState:
    def setup_method(self):
        self.state = QAState()
        self.names = {"uuid1": "Alice", "uuid2": "Bob", "__host__": "Host"}
        self.avatars = {"uuid1": "avatar1.png", "uuid2": "avatar2.png"}

    def test_submit_creates_question(self):
        qid = self.state.submit("uuid1", "What is Python?")
        assert qid in self.state.questions
        q = self.state.questions[qid]
        assert q["text"] == "What is Python?"
        assert q["author"] == "uuid1"
        assert q["upvoters"] == set()
        assert q["answered"] is False

    def test_upvote_success(self):
        qid = self.state.submit("uuid1", "Question")
        success, author = self.state.upvote(qid, "uuid2")
        assert success is True
        assert author == "uuid1"
        assert "uuid2" in self.state.questions[qid]["upvoters"]

    def test_upvote_self_rejected(self):
        qid = self.state.submit("uuid1", "Question")
        success, _ = self.state.upvote(qid, "uuid1")
        assert success is False

    def test_upvote_duplicate_rejected(self):
        qid = self.state.submit("uuid1", "Question")
        self.state.upvote(qid, "uuid2")
        success, _ = self.state.upvote(qid, "uuid2")
        assert success is False

    def test_upvote_nonexistent_rejected(self):
        success, _ = self.state.upvote("bad-id", "uuid1")
        assert success is False

    def test_edit_text(self):
        qid = self.state.submit("uuid1", "Original")
        assert self.state.edit_text(qid, "Edited") is True
        assert self.state.questions[qid]["text"] == "Edited"

    def test_edit_nonexistent(self):
        assert self.state.edit_text("bad-id", "text") is False

    def test_delete(self):
        qid = self.state.submit("uuid1", "Question")
        assert self.state.delete(qid) is True
        assert qid not in self.state.questions

    def test_delete_nonexistent(self):
        assert self.state.delete("bad-id") is False

    def test_toggle_answered(self):
        qid = self.state.submit("uuid1", "Question")
        assert self.state.toggle_answered(qid, True) is True
        assert self.state.questions[qid]["answered"] is True
        assert self.state.toggle_answered(qid, False) is True
        assert self.state.questions[qid]["answered"] is False

    def test_clear(self):
        self.state.submit("uuid1", "Q1")
        self.state.submit("uuid2", "Q2")
        self.state.clear()
        assert self.state.questions == {}

    def test_build_question_list_resolves_names(self):
        self.state.submit("uuid1", "Question")
        result = self.state.build_question_list(self.names, self.avatars)
        assert len(result) == 1
        assert result[0]["author"] == "Alice"
        assert result[0]["author_uuid"] == "uuid1"
        assert result[0]["author_avatar"] == "avatar1.png"

    def test_build_question_list_sorted_by_upvotes(self):
        q1 = self.state.submit("uuid1", "Less popular")
        q2 = self.state.submit("uuid2", "More popular")
        self.state.upvote(q2, "uuid1")
        result = self.state.build_question_list(self.names, self.avatars)
        assert result[0]["text"] == "More popular"
        assert result[1]["text"] == "Less popular"

    def test_build_question_list_upvoters_as_list(self):
        qid = self.state.submit("uuid1", "Question")
        self.state.upvote(qid, "uuid2")
        result = self.state.build_question_list(self.names, self.avatars)
        assert isinstance(result[0]["upvoters"], list)
        assert result[0]["upvote_count"] == 1

    def test_sync_from_restore(self):
        data = {
            "qa_questions": {
                "q1": {
                    "id": "q1", "text": "Q1", "author": "uuid1",
                    "upvoters": ["uuid2"], "answered": True,
                    "timestamp": 1234.0,
                },
            },
        }
        self.state.sync_from_restore(data)
        assert "q1" in self.state.questions
        assert self.state.questions["q1"]["upvoters"] == {"uuid2"}
        assert self.state.questions["q1"]["answered"] is True
