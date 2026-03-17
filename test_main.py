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

import json
import pytest
from contextlib import contextmanager
from fastapi.testclient import TestClient

from main import app, state


# ---------------------------------------------------------------------------
# DSL
# ---------------------------------------------------------------------------

class ParticipantSession:
    """
    Wraps a WebSocket connection for one participant.
    Provides readable assertion helpers.
    """

    def __init__(self, ws, name: str):
        self._ws = ws
        self.name = name
        self._last_state: dict = {}
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
        self._client = TestClient(app)

    # ── Poll management ──

    def create_poll(self, question: str, options: list[str], multi: bool = False) -> dict:
        resp = self._client.post("/api/poll", json={"question": question, "options": options, "multi": multi})
        assert resp.status_code == 200, f"create_poll failed: {resp.text}"
        return resp.json()["poll"]

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
        with self._client.websocket_connect(f"/ws/{name}") as ws:
            yield ParticipantSession(ws, name)

    def suggest_name(self) -> str:
        return self._client.get("/api/suggest-name").json()["name"]


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
            assert state.locations.get("Alice") == "Bucharest, Romania"


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
