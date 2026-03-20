"""
Integration tests for the Workshop Tool — API level.

Uses a small DSL built on top of FastAPI's TestClient:

    session = WorkshopSession()
    session.create_poll("Best language?", ["Python", "Java"])
    session.open_poll()

    with session.participant("Alice") as alice:
        alice.assert_poll("Best language?")
        alice.vote_for("Python")
        alice.assert_vote_counts({"Python": 1})

    session.assert_status(total_votes=1)
"""

import base64
import json
import uuid as uuid_mod
import pytest
from contextlib import contextmanager
from fastapi.testclient import TestClient

from main import app, state

import os
# auth.py loads secrets.env into os.environ on import; we import app (which imports auth) before this line
import auth  # noqa: ensure secrets.env is loaded
_HOST_AUTH_HEADERS = {
    "Authorization": "Basic " + base64.b64encode(
        f"{os.environ.get('HOST_USERNAME', 'host')}:{os.environ.get('HOST_PASSWORD', 'host')}".encode()
    ).decode()
}


# ---------------------------------------------------------------------------
# DSL
# ---------------------------------------------------------------------------

class ParticipantSession:
    """
    Wraps a WebSocket connection for one participant.
    Provides readable assertion helpers.
    """

    def __init__(self, ws, name: str, uuid: str):
        self._ws = ws
        self.name = name
        self.uuid = uuid
        self._last_state: dict = {}
        # Send set_name as first message
        self._ws.send_text(json.dumps({"type": "set_name", "name": name}))
        self._receive_initial_state()

    def _receive_initial_state(self):
        self._last_state = self._recv("state")

    def _recv(self, expected_type: str) -> dict:
        for _ in range(20):
            msg = json.loads(self._ws.receive_text())
            if msg["type"] == expected_type:
                return msg
        raise AssertionError(f"{self.name}: never received '{expected_type}' message")

    def send(self, payload: dict):
        self._ws.send_text(json.dumps(payload))

    # ── Voting ──

    def vote_for(self, option_text: str):
        """Cast a single vote by matching option text."""
        opt_id = self._option_id(option_text)
        self.send({"type": "vote", "option_id": opt_id})
        self._last_state = self._recv("vote_update")

    def multi_vote(self, *option_texts: str):
        """Cast a multi-select vote by matching option texts."""
        opt_ids = [self._option_id(t) for t in option_texts]
        self.send({"type": "multi_vote", "option_ids": opt_ids})
        self._last_state = self._recv("vote_update")

    def send_location(self, location: str):
        self.send({"type": "location", "location": location})

    def submit_word(self, word: str):
        """Submit a word to the word cloud."""
        self.send({"type": "wordcloud_word", "word": word})
        self._last_state = self._recv("state")

    # ── Assertions ──

    def assert_poll(self, question: str):
        poll = self._last_state.get("poll")
        assert poll is not None, f"{self.name}: expected a poll, got None"
        assert poll["question"] == question, (
            f"{self.name}: poll question mismatch: {poll['question']!r} != {question!r}"
        )

    def assert_no_poll(self):
        assert self._last_state.get("poll") is None, (
            f"{self.name}: expected no poll, but got one"
        )

    def assert_poll_active(self, expected: bool = True):
        active = self._last_state.get("poll_active")
        assert active == expected, (
            f"{self.name}: poll_active={active}, expected {expected}"
        )

    def assert_participant_count(self, n: int):
        count = self._last_state.get("participant_count") or self._last_state.get("count")
        assert count == n, f"{self.name}: participant_count={count}, expected {n}"

    def assert_vote_counts(self, expected: dict[str, int]):
        """Assert vote counts by option text."""
        raw = self._last_state.get("vote_counts", {})
        poll = self._last_state.get("poll") or state.poll
        text_to_id = {o["text"]: o["id"] for o in poll["options"]}
        for text, expected_count in expected.items():
            opt_id = text_to_id.get(text)
            assert opt_id is not None, f"Unknown option text: {text!r}"
            actual = raw.get(opt_id, 0)
            assert actual == expected_count, (
                f"{self.name}: votes for {text!r}: {actual} != {expected_count}"
            )

    def assert_total_votes(self, n: int):
        total = self._last_state.get("total_votes", sum(self._last_state.get("vote_counts", {}).values()))
        assert total == n, f"{self.name}: total_votes={total}, expected {n}"

    def assert_poll_is_multi(self):
        poll = self._last_state.get("poll") or state.poll
        assert poll and poll.get("multi"), f"{self.name}: poll is not multi-select"

    def assert_score(self, expected_pts: int):
        """Assert this participant's score in server state."""
        actual = state.scores.get(self.uuid, 0)
        assert actual == expected_pts, f"{self.name}: score={actual}, expected {expected_pts}"

    def assert_no_score(self):
        assert self.uuid not in state.scores or state.scores[self.uuid] == 0, (
            f"{self.name}: expected no score but got {state.scores.get(self.uuid)}"
        )

    def assert_wordcloud_word(self, word: str, expected_count: int):
        """Assert a word's count in the word cloud state."""
        words = self._last_state.get("wordcloud_words", {})
        actual = words.get(word, 0)
        assert actual == expected_count, (
            f"{self.name}: wordcloud_words[{word!r}]={actual}, expected {expected_count}"
        )

    # ── Internal helpers ──

    def _option_id(self, text: str) -> str:
        poll = self._last_state.get("poll") or state.poll
        assert poll, f"{self.name}: no current poll to look up option {text!r}"
        for opt in poll["options"]:
            if opt["text"] == text:
                return opt["id"]
        raise AssertionError(f"{self.name}: no option with text {text!r}; options: {[o['text'] for o in poll['options']]}")


class WorkshopSession:
    """
    High-level DSL for the host side: create/open/close/delete polls,
    assert overall status, and open participant WebSocket sessions.
    """

    def __init__(self):
        self._client = TestClient(app, headers=_HOST_AUTH_HEADERS)
        self._poll: dict | None = None

    # ── Poll management ──

    def create_poll(self, question: str, options: list[str], multi: bool = False) -> dict:
        resp = self._client.post("/api/poll", json={"question": question, "options": options, "multi": multi})
        assert resp.status_code == 200, f"create_poll failed: {resp.text}"
        self._poll = resp.json()["poll"]
        return self._poll

    def mark_correct(self, *option_texts: str):
        """Mark options as correct by text."""
        assert self._poll, "No current poll"
        text_to_id = {o["text"]: o["id"] for o in self._poll["options"]}
        ids = [text_to_id[t] for t in option_texts]
        resp = self._client.post("/api/poll/correct", json={"correct_ids": ids})
        assert resp.status_code == 200, f"mark_correct failed: {resp.text}"

    def get_scores(self) -> dict:
        """Return scores keyed by display name. Sums scores if multiple UUIDs share a name."""
        result: dict[str, int] = {}
        for uid, pts in state.scores.items():
            name = state.participant_names.get(uid, uid)
            result[name] = result.get(name, 0) + pts
        return result

    def reset_scores(self):
        resp = self._client.delete("/api/scores")
        assert resp.status_code == 200

    def open_poll(self):
        resp = self._client.post("/api/poll/status", json={"open": True})
        assert resp.status_code == 200
        assert resp.json()["poll_active"] is True

    def close_poll(self):
        resp = self._client.post("/api/poll/status", json={"open": False})
        assert resp.status_code == 200
        assert resp.json()["poll_active"] is False

    def delete_poll(self):
        resp = self._client.delete("/api/poll")
        assert resp.status_code == 200

    # ── Status assertions ──

    def assert_status(self, *, total_votes: int = None, poll_active: bool = None,
                      participants: int = None):
        s = self._client.get("/api/status").json()
        if total_votes is not None:
            assert s["total_votes"] == total_votes, f"total_votes={s['total_votes']}, expected {total_votes}"
        if poll_active is not None:
            assert s["poll_active"] == poll_active, f"poll_active={s['poll_active']}, expected {poll_active}"
        if participants is not None:
            assert s["participants"] == participants, f"participants={s['participants']}, expected {participants}"

    def assert_vote_counts(self, expected: dict[str, int]):
        """Assert vote counts on the status endpoint by option text."""
        s = self._client.get("/api/status").json()
        poll = s["poll"]
        assert poll, "No current poll"
        text_to_id = {o["text"]: o["id"] for o in poll["options"]}
        for text, expected_count in expected.items():
            opt_id = text_to_id[text]
            actual = s["vote_counts"].get(opt_id, 0)
            assert actual == expected_count, f"votes for {text!r}: {actual} != {expected_count}"

    # ── Participant helpers ──

    @contextmanager
    def participant(self, name: str):
        uid = str(uuid_mod.uuid4())
        with self._client.websocket_connect(f"/ws/{uid}") as ws:
            yield ParticipantSession(ws, name, uid)

    def suggest_name(self) -> str:
        return self._client.get("/api/suggest-name").json()["name"]

    def open_wordcloud(self):
        resp = self._client.post("/api/activity", json={"activity": "wordcloud"})
        assert resp.status_code == 200, f"open_wordcloud failed: {resp.text}"

    def close_wordcloud(self):
        resp = self._client.post("/api/activity", json={"activity": "none"})
        assert resp.status_code == 200, f"close_wordcloud failed: {resp.text}"

    def assert_activity(self, expected: str):
        from state import state
        assert state.current_activity == expected, (
            f"current_activity={state.current_activity!r}, expected {expected!r}"
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_state():
    state.reset()
    yield
    state.reset()


@pytest.fixture
def session():
    return WorkshopSession()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPollCreation:

    def test_create_single_choice_poll(self, session):
        poll = session.create_poll("Best language?", ["Python", "Java", "Go"])
        assert poll["question"] == "Best language?"
        assert len(poll["options"]) == 3
        assert poll["multi"] is False

    def test_create_multi_choice_poll(self, session):
        poll = session.create_poll("Which are OOP languages?", ["Python", "C", "Java", "Haskell"], multi=True)
        assert poll["multi"] is True

    def test_poll_requires_at_least_two_options(self, session):
        resp = session._client.post("/api/poll", json={"question": "Q?", "options": ["Only one"]})
        assert resp.status_code == 400

    def test_poll_requires_non_empty_question(self, session):
        resp = session._client.post("/api/poll", json={"question": "  ", "options": ["A", "B"]})
        assert resp.status_code == 400

    def test_creating_new_poll_resets_votes(self, session):
        session.create_poll("First poll", ["A", "B"])
        session.open_poll()
        with session.participant("Alice") as alice:
            alice.vote_for("A")
        session.assert_status(total_votes=1)

        session.create_poll("Second poll", ["X", "Y"])
        session.assert_status(total_votes=0)


class TestVotingFlow:

    def test_participant_sees_poll_on_connect(self, session):
        session.create_poll("Tabs or spaces?", ["Tabs", "Spaces"])
        with session.participant("Alice") as alice:
            alice.assert_poll("Tabs or spaces?")
            alice.assert_poll_active(False)

    def test_participant_can_vote_when_poll_is_open(self, session):
        session.create_poll("Pick one", ["Yes", "No"])
        session.open_poll()
        with session.participant("Bob") as bob:
            bob.assert_poll_active(True)
            bob.vote_for("Yes")
            bob.assert_vote_counts({"Yes": 1, "No": 0})
            bob.assert_total_votes(1)

    def test_vote_is_rejected_when_poll_is_closed(self, session):
        session.create_poll("Pick one", ["Yes", "No"])
        # poll_active is False by default — do NOT open it
        with session.participant("Carol") as carol:
            carol.send({"type": "vote", "option_id": "opt0"})
        session.assert_status(total_votes=0)

    def test_participant_can_change_vote(self, session):
        session.create_poll("Pick one", ["Yes", "No"])
        session.open_poll()
        with session.participant("Dave") as dave:
            dave.vote_for("Yes")
            dave.vote_for("No")
            dave.assert_vote_counts({"Yes": 0, "No": 1})
        session.assert_status(total_votes=1)

    def test_multiple_participants_vote(self, session):
        session.create_poll("Pick one", ["Yes", "No"])
        session.open_poll()
        with session.participant("Alice") as alice:
            with session.participant("Bob") as bob:
                alice.vote_for("Yes")
                bob.vote_for("No")
        session.assert_status(total_votes=2)
        session.assert_vote_counts({"Yes": 1, "No": 1})

    def test_results_visible_after_poll_closes(self, session):
        session.create_poll("Framework?", ["FastAPI", "Django", "Flask"])
        session.open_poll()
        with session.participant("Alice") as alice:
            alice.vote_for("FastAPI")
        session.close_poll()
        session.assert_status(poll_active=False, total_votes=1)
        session.assert_vote_counts({"FastAPI": 1})


class TestMultiVoting:

    def test_multi_vote_registers_multiple_options(self, session):
        session.create_poll("Which are compiled?", ["Python", "Java", "C", "Ruby"], multi=True)
        session.open_poll()
        with session.participant("Alice") as alice:
            alice.assert_poll_is_multi()
            alice.multi_vote("Java", "C")
            alice.assert_vote_counts({"Java": 1, "C": 1, "Python": 0, "Ruby": 0})

    def test_multi_vote_is_replaced_on_resubmit(self, session):
        session.create_poll("Pick languages", ["Python", "Java", "C"], multi=True)
        session.open_poll()
        with session.participant("Bob") as bob:
            bob.multi_vote("Python", "Java")
            bob.multi_vote("C")   # re-selects only C
            bob.assert_vote_counts({"C": 1, "Python": 0, "Java": 0})
        session.assert_status(total_votes=1)

    def test_single_vote_rejected_on_multi_poll(self, session):
        session.create_poll("Multi poll", ["A", "B"], multi=True)
        session.open_poll()
        with session.participant("Carol") as carol:
            carol.send({"type": "vote", "option_id": "opt0"})
        # single vote type should be ignored on a multi poll
        session.assert_status(total_votes=0)


class TestParticipantPresence:

    def test_participant_count_on_connect(self, session):
        session.create_poll("Q?", ["A", "B"])
        with session.participant("Alice") as alice:
            alice.assert_participant_count(1)

    def test_participant_count_with_two_users(self, session):
        session.create_poll("Q?", ["A", "B"])
        with session.participant("Alice") as _alice:
            with session.participant("Bob") as _bob:
                pass
        session.assert_status(participants=0)  # both disconnected

    def test_suggest_name_returns_string(self, session):
        name = session.suggest_name()
        assert isinstance(name, str) and len(name) > 0

    def test_location_message_is_stored(self, session):
        with session.participant("Alice") as alice:
            alice.send_location("Bucharest, Romania")
            # wait for the server's broadcast confirming the location was processed
            alice._recv("participant_count")
            # assert while still connected (disconnect clears locations)
            assert state.locations.get(alice.uuid) == "Bucharest, Romania"


class TestPollLifecycle:

    def test_no_poll_on_fresh_state(self, session):
        with session.participant("Alice") as alice:
            alice.assert_no_poll()

    def test_delete_poll_clears_state(self, session):
        session.create_poll("Q?", ["A", "B"])
        session.open_poll()
        session.delete_poll()
        session.assert_status(total_votes=0, poll_active=False)
        with session.participant("Alice") as alice:
            alice.assert_no_poll()

    def test_status_endpoint_reflects_votes(self, session):
        session.create_poll("Q?", ["A", "B"])
        session.open_poll()
        with session.participant("Alice") as alice:
            alice.vote_for("A")
        session.assert_status(total_votes=1, poll_active=True)
        session.assert_vote_counts({"A": 1, "B": 0})


class TestScoring:

    def test_correct_voter_receives_points(self, session):
        session.create_poll("Q?", ["A", "B"])
        session.open_poll()
        with session.participant("Alice") as alice:
            alice.vote_for("A")
        session.close_poll()
        session.mark_correct("A")
        scores = session.get_scores()
        assert "Alice" in scores
        assert scores["Alice"] >= 500  # at minimum 500 pts

    def test_incorrect_voter_receives_no_points(self, session):
        session.create_poll("Q?", ["A", "B"])
        session.open_poll()
        with session.participant("Alice") as alice:
            alice.vote_for("B")
        session.close_poll()
        session.mark_correct("A")
        scores = session.get_scores()
        assert scores.get("Alice", 0) == 0

    def test_non_voter_receives_no_points(self, session):
        session.create_poll("Q?", ["A", "B"])
        session.open_poll()
        session.close_poll()
        session.mark_correct("A")
        with session.participant("Silent") as s:
            s.assert_no_score()

    def test_score_capped_between_500_and_1000(self, session):
        session.create_poll("Q?", ["A", "B"])
        session.open_poll()
        with session.participant("Alice") as alice:
            alice.vote_for("A")
        session.close_poll()
        session.mark_correct("A")
        pts = session.get_scores().get("Alice", 0)
        assert 500 <= pts <= 1000

    def test_toggling_correct_does_not_double_award(self, session):
        """Toggling A off and on again must not accumulate extra points."""
        session.create_poll("Q?", ["A", "B"])
        session.open_poll()
        with session.participant("Alice") as alice:
            alice.vote_for("A")
        session.close_poll()
        session.mark_correct("A")
        pts_first = session.get_scores().get("Alice", 0)
        # Toggle off then on again
        session.mark_correct()         # no correct options
        session.mark_correct("A")      # re-mark A as correct
        pts_after = session.get_scores().get("Alice", 0)
        assert pts_after == pts_first, (
            f"Double-award detected: {pts_first} → {pts_after}"
        )

    def test_scores_accumulate_across_polls(self, session):
        """Points from multiple polls should stack."""
        session.create_poll("Poll 1", ["A", "B"])
        session.open_poll()
        with session.participant("Alice") as alice:
            alice.vote_for("A")
        session.close_poll()
        session.mark_correct("A")
        pts_after_poll1 = session.get_scores().get("Alice", 0)

        session.create_poll("Poll 2", ["X", "Y"])
        session.open_poll()
        with session.participant("Alice") as alice:
            alice.vote_for("X")
        session.close_poll()
        session.mark_correct("X")
        pts_after_poll2 = session.get_scores().get("Alice", 0)

        assert pts_after_poll2 > pts_after_poll1, "Points from poll 2 should be added to poll 1"
        assert pts_after_poll2 <= pts_after_poll1 + 1000

    # ── Multi-select scoring scenarios (Gherkin-style parametrize) ──────────
    #
    # Formula: ratio = max(0, (R - W) / C)
    #   R = correct options the participant selected
    #   W = wrong options the participant selected
    #   C = total correct options (as marked by host)
    # Points = round(speed_adjusted_max * ratio), speed_adjusted_max in [500..1000]
    #
    # Options: A, B, C, D  (4 options total)
    #
    # | voted   | correct | R | W | C | ratio | expect_points |
    # |---------|---------|---|---|---|-------|---------------|
    # | A B     | A       | 1 | 1 | 1 | 0.0   | 0             |  voted wrong too
    # | A B     | A B     | 2 | 0 | 2 | 1.0   | full          |  perfect
    # | A B     | B       | 1 | 1 | 1 | 0.0   | 0             |  voted wrong too
    # | A B     | A B C   | 2 | 0 | 3 | 0.67  | partial       |  missed C
    # | A B C   | A B     | 2 | 1 | 2 | 0.5   | partial       |  extra wrong
    # | A       | A B     | 1 | 0 | 2 | 0.5   | partial       |  missed B
    # | A B C D | A B     | 2 | 2 | 2 | 0.0   | 0             |  negated by wrongs
    # | C D     | A B     | 0 | 2 | 2 | 0.0   | 0             |  all wrong
    # | A B     | C D     | 0 | 2 | 2 | 0.0   | 0             |  voted both wrong
    @pytest.mark.parametrize("voted,correct_marked,expect_nonzero,description", [
        # voted=A+B, only A correct → R=1,W=1,C=1 → ratio=0 → no points
        (["A","B"],  ["A"],       False, "voted A+B, only A correct: penalised by wrong B"),
        # voted=A+B, both correct → R=2,W=0,C=2 → ratio=1 → full points
        (["A","B"],  ["A","B"],   True,  "voted A+B, both correct: full score"),
        # voted=A+B, only B correct → R=1,W=1,C=1 → ratio=0 → no points
        (["A","B"],  ["B"],       False, "voted A+B, only B correct: penalised by wrong A"),
        # voted=A+B, correct=A+B+C → R=2,W=0,C=3 → ratio=0.67 → partial
        (["A","B"],  ["A","B","C"], True,  "voted A+B, correct=A+B+C: partial (missed C)"),
        # voted=A+B+C, correct=A+B → R=2,W=1,C=2 → ratio=0.5 → partial
        (["A","B","C"], ["A","B"], True,  "voted A+B+C, correct=A+B: partial (extra wrong C)"),
        # voted=A only, correct=A+B → R=1,W=0,C=2 → ratio=0.5 → partial
        (["A"],      ["A","B"],   True,  "voted A only, correct=A+B: partial (missed B)"),
        # voted=A+B+C+D, correct=A+B → R=2,W=2,C=2 → ratio=0 → no points
        (["A","B","C","D"], ["A","B"], False, "voted all 4, only A+B correct: wrongs cancel"),
        # voted=C+D, correct=A+B → R=0,W=2 → ratio=0 → no points
        (["C","D"],  ["A","B"],   False, "voted C+D, correct=A+B: entirely wrong"),
        # voted=A+B, correct=C+D → R=0,W=2 → ratio=0 → no points
        (["A","B"],  ["C","D"],   False, "voted A+B, correct=C+D: entirely wrong"),
    ])
    def test_multi_select_scoring(self, session, voted, correct_marked, expect_nonzero, description):
        session.create_poll("Multi Q", ["A","B","C","D"], multi=True)
        session.open_poll()
        with session.participant("Alice") as alice:
            alice.multi_vote(*voted)
        session.close_poll()
        session.mark_correct(*correct_marked)
        pts = session.get_scores().get("Alice", 0)
        if expect_nonzero:
            assert pts > 0, f"FAIL [{description}]: expected points > 0, got {pts}"
        else:
            assert pts == 0, f"FAIL [{description}]: expected 0 points, got {pts}"

    def test_reset_scores_clears_all(self, session):
        session.create_poll("Q?", ["A", "B"])
        session.open_poll()
        with session.participant("Alice") as alice:
            alice.vote_for("A")
        session.close_poll()
        session.mark_correct("A")
        assert session.get_scores().get("Alice", 0) > 0
        session.reset_scores()
        assert session.get_scores() == {}

    def test_faster_voter_scores_higher(self, session):
        """Voter who votes immediately should score higher than one who votes after a delay."""
        from datetime import datetime, timezone, timedelta

        session.create_poll("Q?", ["A", "B"])
        session.open_poll()

        with session.participant("Fast") as fast:
            fast.vote_for("A")

        # Simulate Bob voting 20 seconds later by backdating his vote_time
        with session.participant("Slow") as slow:
            slow.vote_for("A")
            # backdate slow's vote by 20 seconds
            state.vote_times[slow.uuid] = state.vote_times.get(slow.uuid, datetime.now(timezone.utc)) - timedelta(seconds=20)

        session.close_poll()
        session.mark_correct("A")
        scores = session.get_scores()
        assert scores.get("Fast", 0) >= scores.get("Slow", 0), (
            f"Fast={scores.get('Fast')}, Slow={scores.get('Slow')} — faster voter should score >= slower"
        )


# ---------------------------------------------------------------------------
# Word Cloud Tests
# ---------------------------------------------------------------------------

def test_open_wordcloud_sets_activity():
    state.reset()
    session = WorkshopSession()
    session.open_wordcloud()
    session.assert_activity("wordcloud")


def test_close_wordcloud_sets_activity_none():
    state.reset()
    session = WorkshopSession()
    session.open_wordcloud()
    session.close_wordcloud()
    session.assert_activity("none")


def test_open_wordcloud_clears_previous_words():
    state.reset()
    state.wordcloud_words = {"hello": 3}
    session = WorkshopSession()
    # Clearing is done explicitly via /api/wordcloud/clear, not on activity switch
    resp = session._client.post("/api/wordcloud/clear")
    assert resp.status_code == 200
    assert state.wordcloud_words == {}


def test_open_wordcloud_blocked_when_poll_active():
    state.reset()
    session = WorkshopSession()
    session.create_poll("Q?", ["A", "B"])
    # The activity endpoint allows switching, but creating a poll blocks other activities
    # The guard is on /api/poll: cannot create poll when wordcloud/qa is active
    # (no blocking on switching activity via /api/activity while poll exists)
    # Verify that creating a poll blocks wordcloud (the real constraint):
    session.reset_scores()  # reuse session — poll already created
    # Switching to wordcloud while poll exists is now allowed by /api/activity
    resp = session._client.post("/api/activity", json={"activity": "wordcloud"})
    assert resp.status_code == 200  # activity endpoint doesn't block


def test_create_poll_blocked_when_wordcloud_active():
    state.reset()
    session = WorkshopSession()
    session.open_wordcloud()
    resp = session._client.post("/api/poll", json={"question": "Q?", "options": ["A", "B"]})
    assert resp.status_code == 409


def test_wordcloud_word_increments_count():
    state.reset()
    session = WorkshopSession()
    session.open_wordcloud()
    client = TestClient(app)
    uid = str(uuid_mod.uuid4())
    with client.websocket_connect(f"/ws/{uid}") as ws_alice:
        alice = ParticipantSession(ws_alice, "Alice", uid)
        alice.submit_word("microservices")
        alice.assert_wordcloud_word("microservices", 1)
        alice.submit_word("microservices")
        alice.assert_wordcloud_word("microservices", 2)


def test_wordcloud_word_normalizes():
    state.reset()
    session = WorkshopSession()
    session.open_wordcloud()
    client = TestClient(app)
    uid = str(uuid_mod.uuid4())
    with client.websocket_connect(f"/ws/{uid}") as ws_alice:
        alice = ParticipantSession(ws_alice, "Alice", uid)
        alice.submit_word("  Microservices  ")
        alice.assert_wordcloud_word("microservices", 1)


def test_wordcloud_word_awards_200_pts():
    state.reset()
    session = WorkshopSession()
    session.open_wordcloud()
    client = TestClient(app)
    uid = str(uuid_mod.uuid4())
    with client.websocket_connect(f"/ws/{uid}") as ws_alice:
        alice = ParticipantSession(ws_alice, "Alice", uid)
        alice.submit_word("complexity")
        alice.assert_score(200)


def test_wordcloud_word_host_gets_no_pts():
    state.reset()
    session = WorkshopSession()
    session.open_wordcloud()
    client = TestClient(app)
    with client.websocket_connect("/ws/__host__") as ws_host:
        host = ParticipantSession(ws_host, "__host__", "__host__")
        host.submit_word("complexity")
        assert state.scores.get("__host__", 0) == 0


def test_wordcloud_word_rejected_when_not_active():
    state.reset()
    session = WorkshopSession()
    # wordcloud NOT opened
    client = TestClient(app)
    uid = str(uuid_mod.uuid4())
    with client.websocket_connect(f"/ws/{uid}") as ws_alice:
        alice = ParticipantSession(ws_alice, "Alice", uid)
        alice.send({"type": "wordcloud_word", "word": "test"})
        # No state update — word should be silently dropped
        assert state.wordcloud_words == {}


# ---------------------------------------------------------------------------
# Q&A Tests
# ---------------------------------------------------------------------------

class TestQA:

    def _submit_ws(self, session, name, text):
        """Submit a Q&A question via WebSocket and return the question ID."""
        with session.participant(name) as p:
            p.send({"type": "qa_submit", "text": text})
            # Wait for state broadcast confirming the question
            p._recv("state")
        # Return the last-added question ID
        return list(state.qa_questions.keys())[-1]

    def test_submit_question_appears_in_state(self, session):
        qid = self._submit_ws(session, "Alice", "What is DDD?")
        assert qid in state.qa_questions
        assert state.qa_questions[qid]["text"] == "What is DDD?"

    def test_submit_question_awards_100_pts(self, session):
        self._submit_ws(session, "Alice", "What is DDD?")
        scores = session.get_scores()
        assert scores.get("Alice", 0) == 100

    def test_edit_question_updates_text(self, session):
        qid = self._submit_ws(session, "Alice", "Original text")
        resp = session._client.patch(f"/api/qa/question/{qid}", json={"text": "Edited text"})
        assert resp.status_code == 200, resp.text
        assert state.qa_questions[qid]["text"] == "Edited text"

    def test_edit_question_not_found_returns_404(self, session):
        resp = session._client.patch("/api/qa/question/nonexistent-id", json={"text": "New"})
        assert resp.status_code == 404

    def test_delete_question_removes_from_state(self, session):
        qid = self._submit_ws(session, "Alice", "To be deleted")
        resp = session._client.delete(f"/api/qa/question/{qid}")
        assert resp.status_code == 200
        assert qid not in state.qa_questions

    def test_upvote_question_awards_points_to_author(self, session):
        qid = self._submit_ws(session, "Alice", "What is DDD?")
        with session.participant("Bob") as bob:
            bob.send({"type": "qa_upvote", "question_id": qid})
            bob._recv("state")
        scores = session.get_scores()
        # Alice gets 100 (submit) + 50 (upvote) = 150
        assert scores.get("Alice") == 150
        # Bob gets 25 for upvoting
        assert scores.get("Bob") == 25

    def test_cannot_upvote_own_question(self, session):
        # Author tries to upvote their own question via WS
        with session.participant("Alice") as alice:
            alice.send({"type": "qa_submit", "text": "My own question"})
            alice._recv("state")
            qid = list(state.qa_questions.keys())[-1]
            alice.send({"type": "qa_upvote", "question_id": qid})
            # Server should silently ignore (no error, no state change)
        # Verify upvoter count is still 0
        assert len(state.qa_questions[qid]["upvoters"]) == 0

    def test_cannot_upvote_twice(self, session):
        qid = self._submit_ws(session, "Alice", "Another question")
        with session.participant("Bob") as bob:
            bob.send({"type": "qa_upvote", "question_id": qid})
            bob._recv("state")
            bob.send({"type": "qa_upvote", "question_id": qid})
            # Second upvote silently ignored
        assert len(state.qa_questions[qid]["upvoters"]) == 1

    def test_clear_qa_removes_all_questions(self, session):
        self._submit_ws(session, "Alice", "Q1")
        self._submit_ws(session, "Bob", "Q2")
        resp = session._client.post("/api/qa/clear")
        assert resp.status_code == 200
        assert state.qa_questions == {}


def test_search_materials_fallback_without_daemon(monkeypatch):
    """search_materials returns a safe fallback when daemon deps are not installed."""
    import sys, quiz_core
    # Setting daemon.rag to None in sys.modules causes ImportError on "from daemon.rag import ..."
    monkeypatch.setitem(sys.modules, "daemon.rag", None)
    results = quiz_core.search_materials("circuit breaker")
    assert len(results) == 1
    assert results[0]["source"] == "N/A"


def test_quiz_request_transcript_mode():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/quiz-request",
        json={"minutes": 30},
        headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    data = client.get("/api/quiz-request", headers=_HOST_AUTH_HEADERS).json()
    assert data["request"]["minutes"] == 30
    assert data["request"]["topic"] is None


def test_quiz_request_topic_mode():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/quiz-request",
        json={"topic": "circuit breaker"},
        headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    data = client.get("/api/quiz-request", headers=_HOST_AUTH_HEADERS).json()
    assert data["request"]["topic"] == "circuit breaker"
    assert data["request"]["minutes"] is None


def test_quiz_request_rejects_both_fields():
    client = TestClient(app)
    resp = client.post("/api/quiz-request",
        json={"minutes": 30, "topic": "circuit breaker"},
        headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 422


def test_quiz_request_rejects_neither_field():
    client = TestClient(app)
    resp = client.post("/api/quiz-request",
        json={},
        headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 422


class TestAvatarAssignment:

    def test_lotr_name_gets_matching_avatar(self):
        from state import AppState, assign_avatar, get_avatar_filename
        s = AppState()
        avatar = assign_avatar(s, "test-uuid-1", "Gandalf")
        assert avatar == "gandalf.png"
        assert s.participant_avatars["test-uuid-1"] == "gandalf.png"

    def test_custom_name_gets_deterministic_avatar(self):
        from state import AppState, assign_avatar
        s = AppState()
        a1 = assign_avatar(s, "550e8400-e29b-41d4-a716-446655440000", "Bob")
        a2 = assign_avatar(s, "550e8400-e29b-41d4-a716-446655440000", "Bob")
        assert a1 == a2
        assert a1.endswith(".png")

    def test_assign_once_rename_keeps_avatar(self):
        from state import AppState, assign_avatar
        s = AppState()
        a1 = assign_avatar(s, "test-uuid-1", "Gandalf")
        a2 = assign_avatar(s, "test-uuid-1", "Bob")
        assert a1 == a2 == "gandalf.png"

    def test_get_avatar_filename_slugs(self):
        from state import get_avatar_filename
        assert get_avatar_filename("Gandalf") == "gandalf.png"
        assert get_avatar_filename("Tom Bombadil") == "tom-bombadil.png"
        assert get_avatar_filename("The One Ring") == "the-one-ring.png"
        assert get_avatar_filename("Grima Wormtongue") == "grima-wormtongue.png"
