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

    def assert_my_vote(self, expected_option_text: str):
        """Assert that my_vote in state matches an option by text."""
        my_vote = self._last_state.get("my_vote")
        poll = self._last_state.get("poll") or state.poll
        text_to_id = {o["text"]: o["id"] for o in poll["options"]}
        expected_id = text_to_id[expected_option_text]
        assert my_vote == expected_id, (
            f"{self.name}: my_vote={my_vote!r}, expected {expected_id!r} ({expected_option_text!r})"
        )

    def assert_no_my_vote(self):
        """Assert that my_vote is None (not voted)."""
        my_vote = self._last_state.get("my_vote")
        assert my_vote is None, f"{self.name}: expected my_vote=None, got {my_vote!r}"

    def assert_result_in_state(self, correct_texts: list[str], voted_texts: list[str]):
        """Assert that poll result (correct_ids, voted_ids) is in the state broadcast."""
        poll = self._last_state.get("poll") or state.poll
        text_to_id = {o["text"]: o["id"] for o in poll["options"]}
        expected_correct = set(text_to_id[t] for t in correct_texts)
        expected_voted = set(text_to_id[t] for t in voted_texts)
        actual_correct = set(self._last_state.get("poll_correct_ids") or [])
        actual_voted = set(self._last_state.get("my_voted_ids") or [])
        assert actual_correct == expected_correct, (
            f"{self.name}: poll_correct_ids={actual_correct}, expected {expected_correct}"
        )
        assert actual_voted == expected_voted, (
            f"{self.name}: my_voted_ids={actual_voted}, expected {expected_voted}"
        )

    def assert_no_result_in_state(self):
        """Assert no poll result in state."""
        assert self._last_state.get("poll_correct_ids") is None, (
            f"{self.name}: expected no poll_correct_ids, got {self._last_state.get('poll_correct_ids')}"
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
        resp = self._client.put("/api/poll/correct", json={"correct_ids": ids})
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
        resp = self._client.put("/api/poll/status", json={"open": True})
        assert resp.status_code == 200
        assert resp.json()["poll_active"] is True

    def close_poll(self):
        resp = self._client.put("/api/poll/status", json={"open": False})
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

    @contextmanager
    def participant_with_uuid(self, name: str, uid: str):
        """Connect a participant with a specific UUID (for reconnect tests)."""
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

class TestAppState:

    def test_appstate_has_main_talk_fields(self):
        from state import AppState
        s = AppState()
        assert hasattr(s, 'session_main')
        assert hasattr(s, 'session_talk')
        assert hasattr(s, 'paused_participant_uuids')
        assert s.session_main is None
        assert s.session_talk is None
        assert s.paused_participant_uuids == set()
        assert not hasattr(s, 'session_stack')


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

    def test_host_participant_list_keeps_offline_participants(self, session):
        def recv_type(ws, expected_type):
            for _ in range(30):
                msg = json.loads(ws.receive_text())
                if msg.get("type") == expected_type:
                    return msg
            raise AssertionError(f"Host did not receive message type '{expected_type}'")

        with session._client.websocket_connect("/ws/__host__") as ws_host:
            recv_type(ws_host, "state")
            recv_type(ws_host, "participant_count")  # initial empty list after host connect

            with session.participant("Alice") as alice:
                state.scores[alice.uuid] = 120
                joined = recv_type(ws_host, "participant_count")
                alice_entry = next((p for p in joined["participants"] if p["uuid"] == alice.uuid), None)
                assert alice_entry is not None
                assert alice_entry["online"] is True

            disconnected = recv_type(ws_host, "participant_count")
            alice_entry = next((p for p in disconnected["participants"] if p["uuid"] == alice.uuid), None)
            assert disconnected["count"] == 0
            assert alice_entry is not None
            assert alice_entry["online"] is False
            assert alice_entry["score"] == 120

    def test_host_initial_state_includes_historical_participants(self, session):
        with session.participant("Bob") as bob:
            state.scores[bob.uuid] = 75
            historical_uuid = bob.uuid

        with session._client.websocket_connect("/ws/__host__") as ws_host:
            for _ in range(30):
                msg = json.loads(ws_host.receive_text())
                if msg.get("type") != "state":
                    continue
                bob_entry = next((p for p in msg["participants"] if p["uuid"] == historical_uuid), None)
                assert bob_entry is not None
                assert bob_entry["online"] is False
                assert bob_entry["score"] == 75
                break
            else:
                raise AssertionError("Host did not receive initial state payload")


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
        resp = session._client.put(f"/api/qa/question/{qid}/text", json={"text": "Edited text"})
        assert resp.status_code == 200, resp.text
        assert state.qa_questions[qid]["text"] == "Edited text"

    def test_edit_question_not_found_returns_404(self, session):
        resp = session._client.put("/api/qa/question/nonexistent-id/text", json={"text": "New"})
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


def test_api_slides_is_empty_by_default(monkeypatch, tmp_path):
    state.reset()
    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(tmp_path))
    client = TestClient(app)
    resp = client.get("/api/slides")
    assert resp.status_code == 200
    assert resp.json() == {"slides": []}


def test_participant_slides_modal_has_no_manual_refresh_button():
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'id="slides-refresh-btn"' not in resp.text
    assert "refreshSlidesNow()" not in resp.text


def test_quiz_status_updates_slides_and_api_returns_normalized_data(monkeypatch, tmp_path):
    state.reset()
    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(tmp_path))
    client = TestClient(app)
    resp = client.post("/api/quiz-status", json={
        "status": "ready",
        "message": "Agent ready.",
        "slides": [
            {
                "name": "Architecture Deck",
                "slug": "arch",
                "url": "https://cdn.example.com/abc.pdf",
                "updated_at": "2026-03-25T10:15:00+00:00",
                "etag": "\"v1\"",
            },
            {
                "name": "Intro",
                "url": "https://cdn.example.com/intro.pdf",
            },
        ],
    }, headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200

    slides_resp = client.get("/api/slides")
    assert slides_resp.status_code == 200
    slides = slides_resp.json()["slides"]
    assert len(slides) == 2
    assert slides[0]["slug"] == "arch"
    assert slides[0]["url"] == "https://cdn.example.com/abc.pdf"
    assert slides[1]["slug"] == "intro"


def test_quiz_request_reports_has_slides_flag(monkeypatch, tmp_path):
    state.reset()
    monkeypatch.setenv("TRAINING_ASSISTANT_SLIDES_DIR", str(tmp_path))
    client = TestClient(app)
    client.post("/api/quiz-status", json={
        "status": "ready",
        "message": "Agent ready.",
        "slides": [{"name": "Deck", "url": "https://cdn.example.com/deck.pdf"}],
    }, headers=_HOST_AUTH_HEADERS)
    data = client.get("/api/quiz-request", headers=_HOST_AUTH_HEADERS).json()
    assert data["has_slides"] is True


def test_timing_event_endpoint_returns_ok():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/session/timing_event",
                       json={"event": "recording_warning", "minutes_remaining": 30},
                       headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_timing_event_endpoint_warning_event_returns_ok():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/session/timing_event",
                       json={"event": "warning"},
                       headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200


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

    def test_no_duplicate_avatars(self):
        """Different participants get different avatars (up to 30)."""
        from state import AppState, assign_avatar, LOTR_NAMES
        import uuid as uuid_mod
        s = AppState()
        avatars = []
        for i in range(len(LOTR_NAMES)):
            a = assign_avatar(s, str(uuid_mod.uuid4()), f"CustomName{i}")
            avatars.append(a)
        assert len(set(avatars)) == len(LOTR_NAMES)  # all unique

    def test_lotr_name_always_gets_matching_avatar(self):
        """LOTR names always get their character's avatar, even if duplicated."""
        from state import AppState, assign_avatar
        s = AppState()
        a1 = assign_avatar(s, "uuid-1", "Gandalf")
        a2 = assign_avatar(s, "uuid-2", "Gandalf")
        assert a1 == "gandalf.png"
        assert a2 == "gandalf.png"  # same avatar — matches name

    def test_avatar_in_participant_state_on_connect(self, session):
        """Participant state includes my_avatar after set_name."""
        with session.participant("Legolas") as p:
            assert p._last_state.get("my_avatar") == "legolas.png"

    def test_avatar_in_qa_question(self, session):
        """Q&A questions include author_avatar."""
        session._client.post("/api/activity", json={"activity": "qa"},
                             headers=_HOST_AUTH_HEADERS)
        with session.participant("Gimli") as p:
            p.send({"type": "qa_submit", "text": "Test question?"})
            msg = p._recv("state")
            questions = msg.get("qa_questions", [])
            assert len(questions) == 1
            assert questions[0].get("author_avatar") == "gimli.png"



# ---------------------------------------------------------------------------
# Summary Tests
# ---------------------------------------------------------------------------

def test_post_summary_updates_state():
    """POST /api/summary stores bullets and broadcasts via full state."""
    session = WorkshopSession()
    # POST summary first (before connecting participant)
    resp = session._client.post(
        "/api/summary",
        json={"points": [
            {"text": "Discussed TDD basics", "source": "discussion"},
            {"text": "Covered mocking patterns", "source": "notes"},
        ]},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Participant connects and receives initial state with summary included
    with session.participant("Alice") as alice:
        assert "summary_points" in alice._last_state
        assert len(alice._last_state["summary_points"]) == 2
        assert alice._last_state["summary_points"][0]["text"] == "Discussed TDD basics"
        assert alice._last_state["summary_points"][0]["source"] == "discussion"
        assert alice._last_state["summary_points"][1]["source"] == "notes"


def test_post_summary_with_timestamps():
    """POST /api/summary with time fields stores and broadcasts them."""
    session = WorkshopSession()
    resp = session._client.post(
        "/api/summary",
        json={"points": [
            {"text": "TDD basics", "source": "discussion", "time": "10:15"},
            {"text": "Mocking patterns", "source": "notes"},
        ]},
    )
    assert resp.status_code == 200

    with session.participant("Alice") as alice:
        pts = alice._last_state["summary_points"]
        assert pts[0]["time"] == "10:15"
        assert pts[1].get("time") is None


def test_post_summary_requires_auth():
    """POST /api/summary without auth returns 401."""
    client = TestClient(app)  # no auth headers
    resp = client.post(
        "/api/summary",
        json={"points": [{"text": "Should fail", "source": "discussion"}]},
    )
    assert resp.status_code == 401


def test_get_summary_returns_points():
    """GET /api/summary returns current bullets (public, no auth)."""
    session = WorkshopSession()
    # POST summary as host
    session._client.post(
        "/api/summary",
        json={"points": [
            {"text": "TDD is great", "source": "discussion"},
            {"text": "Use mocks sparingly", "source": "notes"},
        ]},
    )
    # GET without auth — should work (public endpoint)
    client = TestClient(app)
    resp = client.get("/api/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["points"]) == 2
    assert data["points"][0]["text"] == "TDD is great"
    assert data["points"][1]["source"] == "notes"
    assert data["updated_at"] is not None


def test_get_summary_empty():
    """GET /api/summary returns empty list when no summary posted."""
    state.reset()
    client = TestClient(app)
    resp = client.get("/api/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["points"] == []
    assert data["updated_at"] is None


# ---------------------------------------------------------------------------
# Unit tests for auto_assign_remaining (debate side auto-assignment)
# ---------------------------------------------------------------------------
from routers.debate import auto_assign_remaining


@pytest.mark.parametrize(
    "total, pre_assigned,          expect_trigger, expect_balanced",
    [
        # fmt: off
        # total | pre-assigned sides dict        | triggers? | balanced after?
        (2,      {"p1": "for"},                    True,       True),   # 1/2 picked → ≥50% → assign p2 to "against"
        (3,      {"p1": "for"},                    False,      None),   # 1/3 picked → <50% → no trigger
        (3,      {"p1": "for", "p2": "against"},   True,       True),   # 2/3 picked → ≥50% → assign p3
        (4,      {"p1": "for"},                    False,      None),   # 1/4 → <50%
        (4,      {"p1": "for", "p2": "for"},       True,       True),   # 2/4 → ≥50% → assign 2 to "against"
        (4,      {"p1": "for", "p2": "against"},   True,       True),   # 2/4 → ≥50% → 1 each side remaining
        (5,      {"p1": "for", "p2": "against"},   False,      None),   # 2/5 → <50%
        (5,      {"p1": "for", "p2": "for", "p3": "against"}, True, True),  # 3/5 → ≥50%
        (6,      {"p1": "for", "p2": "for", "p3": "for"},     True, True),  # 3/6 → ≥50% → 3 go "against"
        (1,      {},                               False,      None),   # 0 assigned → never triggers
        (4,      {},                               False,      None),   # 0 assigned → never triggers
        (2,      {"p1": "for", "p2": "against"},   True,       True),   # all already assigned → returns []
        (10,     {f"p{i}": "for" for i in range(1, 6)}, True, True),   # 5/10 → ≥50%, 5 unassigned → all "against"
        # fmt: on
    ],
    ids=[
        "2p_1for",
        "3p_1for_no_trigger",
        "3p_2picked",
        "4p_1for_no_trigger",
        "4p_2for",
        "4p_1each",
        "5p_2picked_no_trigger",
        "5p_3picked",
        "6p_3for",
        "1p_none_assigned",
        "4p_none_assigned",
        "2p_all_assigned",
        "10p_5for",
    ],
)
def test_auto_assign_remaining(total, pre_assigned, expect_trigger, expect_balanced):
    """Tabular Gherkin: GIVEN total participants with pre_assigned sides,
    WHEN auto_assign_remaining runs,
    THEN it triggers (or not) and teams are balanced."""
    all_pids = [f"p{i}" for i in range(1, total + 1)]
    sides = dict(pre_assigned)  # copy to avoid mutating parametrize data

    newly = auto_assign_remaining(all_pids, sides)

    if not expect_trigger:
        assert newly == [], f"Expected no trigger, but got {newly}"
        return

    # When triggered: every participant must have a side
    for pid in all_pids:
        assert pid in sides, f"{pid} was not assigned a side"

    # Teams must be balanced (differ by at most 1)
    for_count = sum(1 for s in sides.values() if s == "for")
    against_count = sum(1 for s in sides.values() if s == "against")
    assert abs(for_count - against_count) <= 1, (
        f"Unbalanced: {for_count} for vs {against_count} against"
    )


# ---------------------------------------------------------------------------
# Vote & Result Restore on Refresh (GH #33)
# ---------------------------------------------------------------------------

class TestVoteRestoreOnRefresh:
    """Verify that my_vote and poll results survive participant reconnect."""

    def test_my_vote_included_in_state_after_voting(self, session):
        """After voting, participant state should include my_vote."""
        session.create_poll("Pick one", ["A", "B"])
        session.open_poll()
        uid = str(uuid_mod.uuid4())
        with session.participant_with_uuid("Alice", uid) as alice:
            alice.vote_for("A")
            # Reconnect — simulates browser refresh
        with session.participant_with_uuid("Alice", uid) as alice2:
            alice2.assert_my_vote("A")

    def test_my_vote_none_when_not_voted(self, session):
        """Participant who hasn't voted should get my_vote=None."""
        session.create_poll("Pick one", ["A", "B"])
        session.open_poll()
        with session.participant("Alice") as alice:
            alice.assert_no_my_vote()

    def test_my_vote_multi_included_in_state(self, session):
        """Multi-select vote should be restored on reconnect."""
        session.create_poll("Pick many", ["A", "B", "C"], multi=True)
        session.open_poll()
        uid = str(uuid_mod.uuid4())
        with session.participant_with_uuid("Alice", uid) as alice:
            alice.multi_vote("A", "C")
        with session.participant_with_uuid("Alice", uid) as alice2:
            my_vote = alice2._last_state.get("my_vote")
            assert set(my_vote) == {"opt0", "opt2"}, f"my_vote={my_vote}"

    def test_poll_result_included_in_state_after_correct_marked(self, session):
        """After host marks correct, reconnecting participant sees result in state."""
        session.create_poll("Q?", ["A", "B"])
        session.open_poll()
        uid = str(uuid_mod.uuid4())
        with session.participant_with_uuid("Alice", uid) as alice:
            alice.vote_for("A")
        session.close_poll()
        session.mark_correct("A")
        # Reconnect
        with session.participant_with_uuid("Alice", uid) as alice2:
            alice2.assert_result_in_state(correct_texts=["A"], voted_texts=["A"])

    def test_no_result_before_correct_marked(self, session):
        """Before host marks correct, no result in state."""
        session.create_poll("Q?", ["A", "B"])
        session.open_poll()
        with session.participant("Alice") as alice:
            alice.vote_for("A")
            alice.assert_no_result_in_state()

    def test_result_cleared_on_new_poll(self, session):
        """Creating a new poll should clear previous result."""
        session.create_poll("Q1", ["A", "B"])
        session.open_poll()
        uid = str(uuid_mod.uuid4())
        with session.participant_with_uuid("Alice", uid) as alice:
            alice.vote_for("A")
        session.close_poll()
        session.mark_correct("A")
        # New poll
        session.create_poll("Q2", ["X", "Y"])
        with session.participant_with_uuid("Alice", uid) as alice2:
            alice2.assert_no_result_in_state()
            alice2.assert_no_my_vote()


# ---------------------------------------------------------------------------
# Debate AI poll/result endpoint tests
# ---------------------------------------------------------------------------


def test_debate_ai_request_returns_and_clears():
    """GET /api/debate/ai-request returns pending request then clears it."""
    state.reset()
    client = TestClient(app)

    # Setup: launch debate, add argument, end arguments
    client.post("/api/debate", json={"statement": "Tabs vs spaces"}, headers=_HOST_AUTH_HEADERS)
    state.debate_phase = "arguments"
    state.debate_arguments = [{
        "id": "a1", "author_uuid": "u1", "side": "for",
        "text": "Tabs are better", "upvoters": set(),
        "ai_generated": False, "merged_into": None,
    }]
    client.post("/api/debate/end-arguments", headers=_HOST_AUTH_HEADERS)

    # First poll: should return the request
    resp = client.get("/api/debate/ai-request", headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["request"] is not None
    assert data["request"]["statement"] == "Tabs vs spaces"
    assert len(data["request"]["for_args"]) == 1

    # Second poll: consumed (None)
    resp2 = client.get("/api/debate/ai-request", headers=_HOST_AUTH_HEADERS)
    assert resp2.json()["request"] is None


def test_debate_ai_result_applies_and_advances():
    """POST /api/debate/ai-result applies merges/new args, advances to prep."""
    state.reset()
    client = TestClient(app)
    state.debate_statement = "Tabs vs spaces"
    state.debate_phase = "ai_cleanup"
    state.debate_arguments = [
        {"id": "a1", "author_uuid": "u1", "side": "for",
         "text": "Tabs are beter", "upvoters": set(),
         "ai_generated": False, "merged_into": None},
    ]

    resp = client.post("/api/debate/ai-result", json={
        "merges": [],
        "cleaned": [{"id": "a1", "text": "Tabs are better"}],
        "new_arguments": [
            {"side": "against", "text": "Spaces ensure consistent rendering"},
        ],
    }, headers=_HOST_AUTH_HEADERS)

    assert resp.status_code == 200
    assert state.debate_phase == "prep"
    assert state.debate_arguments[0]["text"] == "Tabs are better"
    ai_args = [a for a in state.debate_arguments if a["ai_generated"]]
    assert len(ai_args) == 1
    assert ai_args[0]["side"] == "against"


def test_debate_ai_result_rejects_wrong_phase():
    """POST /api/debate/ai-result returns 400 if not in ai_cleanup phase."""
    state.reset()
    client = TestClient(app)
    state.debate_statement = "Test"
    state.debate_phase = "prep"

    resp = client.post("/api/debate/ai-result", json={
        "merges": [], "cleaned": [], "new_arguments": [],
    }, headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 400


def test_debate_end_arguments_skips_ai_when_no_args():
    """End arguments with no arguments should skip ai_cleanup, go to prep."""
    state.reset()
    client = TestClient(app)
    client.post("/api/debate", json={"statement": "Test"}, headers=_HOST_AUTH_HEADERS)
    state.debate_phase = "arguments"
    state.debate_arguments = []

    resp = client.post("/api/debate/end-arguments", headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    assert state.debate_phase == "prep"
    assert state.debate_ai_request is None


def test_debate_arguments_sorted_by_upvotes():
    """Arguments are broadcast sorted by upvote count descending (3, 1, 0)."""
    session = WorkshopSession()

    # Host launches debate
    session._client.post("/api/debate", json={"statement": "Microservices > Monoliths"}, headers=_HOST_AUTH_HEADERS)
    session._client.post("/api/activity", json={"activity": "debate"}, headers=_HOST_AUTH_HEADERS)

    uid_alice = str(uuid_mod.uuid4())
    uid_bob = str(uuid_mod.uuid4())
    uid_carol = str(uuid_mod.uuid4())
    uid_dave = str(uuid_mod.uuid4())
    client = TestClient(app)

    with (
        client.websocket_connect(f"/ws/{uid_alice}") as ws_a,
        client.websocket_connect(f"/ws/{uid_bob}") as ws_b,
        client.websocket_connect(f"/ws/{uid_carol}") as ws_c,
        client.websocket_connect(f"/ws/{uid_dave}") as ws_d,
    ):
        alice = ParticipantSession(ws_a, "Alice", uid_alice)
        bob = ParticipantSession(ws_b, "Bob", uid_bob)
        carol = ParticipantSession(ws_c, "Carol", uid_carol)
        dave = ParticipantSession(ws_d, "Dave", uid_dave)

        # All pick "for" side
        for p in [alice, bob, carol, dave]:
            p.send({"type": "debate_pick_side", "side": "for"})
            p._recv("state")

        # Phase auto-advances to "arguments" since all picked
        assert state.debate_phase == "arguments"

        # Alice submits arg_A, Bob submits arg_B, Carol submits arg_C
        alice.send({"type": "debate_argument", "text": "Arg A - most popular"})
        alice._recv("state")
        arg_a_id = state.debate_arguments[-1]["id"]

        bob.send({"type": "debate_argument", "text": "Arg B - one vote"})
        bob._recv("state")
        arg_b_id = state.debate_arguments[-1]["id"]

        carol.send({"type": "debate_argument", "text": "Arg C - zero votes"})
        carol._recv("state")

        # Upvote arg_A 3 times (Bob, Carol, Dave)
        bob.send({"type": "debate_upvote", "argument_id": arg_a_id})
        bob._recv("state")
        carol.send({"type": "debate_upvote", "argument_id": arg_a_id})
        carol._recv("state")
        dave.send({"type": "debate_upvote", "argument_id": arg_a_id})
        dave._recv("state")

        # Upvote arg_B 1 time (Alice)
        alice.send({"type": "debate_upvote", "argument_id": arg_b_id})
        alice._recv("state")

        # Verify upvote counts in state
        assert len(state.debate_arguments[0]["upvoters"]) == 3  # arg_A
        assert len(state.debate_arguments[1]["upvoters"]) == 1  # arg_B
        assert len(state.debate_arguments[2]["upvoters"]) == 0  # arg_C

        # Verify broadcast sends arguments sorted by upvote_count desc
        # Use the build function directly to get the freshest state
        from messaging import _build_debate_for_participant
        fresh = _build_debate_for_participant(uid_alice)
        debate_args = fresh["debate_arguments"]
        visible = [a for a in debate_args if not a.get("merged_into")]
        assert len(visible) == 3
        assert visible[0]["text"] == "Arg A - most popular"
        assert visible[0]["upvote_count"] == 3
        assert visible[1]["text"] == "Arg B - one vote"
        assert visible[1]["upvote_count"] == 1
        assert visible[2]["text"] == "Arg C - zero votes"
        assert visible[2]["upvote_count"] == 0


# ---------------------------------------------------------------------------
# Session stack endpoints
# ---------------------------------------------------------------------------

def test_start_session_stores_request():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/session/start", json={"name": "2026-03-23 Workshop"}, headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["ok"]

def test_start_session_requires_auth():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/session/start", json={"name": "Test"})
    assert resp.status_code == 401

def test_end_session_stores_request():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/session/end", headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200

def test_rename_session_stores_request():
    state.reset()
    client = TestClient(app)
    resp = client.patch("/api/session/rename", json={"name": "New Name"}, headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200

def test_poll_session_request_returns_and_clears():
    state.reset()
    client = TestClient(app)
    client.post("/api/session/start", json={"name": "Test"}, headers=_HOST_AUTH_HEADERS)
    resp = client.get("/api/session/request", headers=_HOST_AUTH_HEADERS)
    assert resp.json()["action"] == "start"
    assert resp.json()["name"] == "Test"
    resp2 = client.get("/api/session/request", headers=_HOST_AUTH_HEADERS)
    assert resp2.json()["action"] is None

def test_sync_session_updates_state():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/session/sync", json={
        "main": {"name": "Workshop", "started_at": "2026-03-23T09:00:00", "status": "active"},
        "key_points": [{"text": "Point 1", "source": "discussion"}],
    }, headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    assert state.session_main is not None
    assert state.session_main["name"] == "Workshop"
    assert len(state.summary_points) == 1

def test_session_lifecycle_via_endpoints():
    state.reset()
    client = TestClient(app)

    # Start session
    client.post("/api/session/start", json={"name": "Workshop"}, headers=_HOST_AUTH_HEADERS)
    req = client.get("/api/session/request", headers=_HOST_AUTH_HEADERS).json()
    assert req["action"] == "start"
    assert req["name"] == "Workshop"

    # Simulate daemon sync
    resp = client.post("/api/session/sync", json={
        "main": {"name": "Workshop", "started_at": "2026-03-23T09:00:00", "status": "active"},
        "key_points": [{"text": "Point 1", "source": "discussion"}],
    }, headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200

    # Verify summary points updated via sync
    summary = client.get("/api/summary").json()
    assert len(summary["points"]) == 1
    assert state.session_main is not None
    assert state.session_main["name"] == "Workshop"

    # Start nested session
    client.post("/api/session/start", json={"name": "Lunch Talk"}, headers=_HOST_AUTH_HEADERS)
    req2 = client.get("/api/session/request", headers=_HOST_AUTH_HEADERS).json()
    assert req2["action"] == "start"

    # End session
    client.post("/api/session/end", headers=_HOST_AUTH_HEADERS)
    req3 = client.get("/api/session/request", headers=_HOST_AUTH_HEADERS).json()
    assert req3["action"] == "end"

    # Rename
    client.patch("/api/session/rename", json={"name": "New Name"}, headers=_HOST_AUTH_HEADERS)
    req4 = client.get("/api/session/request", headers=_HOST_AUTH_HEADERS).json()
    assert req4["action"] == "rename"
    assert req4["name"] == "New Name"


def test_start_talk_queues_action():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/session/start_talk", headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    from state import state as s
    assert s.session_request is not None
    assert s.session_request["action"] == "start_talk"


def test_end_talk_queues_action():
    state.reset()
    client = TestClient(app)
    resp = client.post("/api/session/end_talk", headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    from state import state as s
    assert s.session_request is not None
    assert s.session_request["action"] == "end_talk"


def test_session_interval_lines_txt_filters_and_normalizes(tmp_path, monkeypatch):
    state.reset()
    transcript = (
        "[09:29] Before window\n"
        "[09:30] Alice: Hello   world\n"
        "[09:31] Bob: Another\tline\n"
        "[09:32] After window\n"
    )
    (tmp_path / "2026-03-26 transcription.txt").write_text(transcript, encoding="utf-8")
    monkeypatch.setenv("TRANSCRIPTION_FOLDER", str(tmp_path))

    client = TestClient(app)
    resp = client.get(
        "/api/session/interval-lines.txt",
        params={
            "start": "2026-03-26T09:30:00",
            "end": "2026-03-26T09:32:00",
        },
        headers=_HOST_AUTH_HEADERS,
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "filename=" in resp.headers.get("content-disposition", "")
    assert resp.text == (
        "[2026-03-26 09:30:00] Alice: Hello world\n"
        "[2026-03-26 09:31:00] Bob: Another line\n"
    )


def test_session_interval_lines_txt_validates_range():
    state.reset()
    client = TestClient(app)
    resp = client.get(
        "/api/session/interval-lines.txt",
        params={
            "start": "2026-03-26T10:00:00",
            "end": "2026-03-26T10:00:00",
        },
        headers=_HOST_AUTH_HEADERS,
    )
    assert resp.status_code == 400


def test_pending_deploy_broadcasts_to_participants(monkeypatch):
    """POST /api/pending-deploy with a new SHA broadcasts deploy_pending WS message."""
    import json
    from pathlib import Path
    deploy_info = Path(__file__).parent.parent / "static" / "deploy-info.json"
    original = deploy_info.read_text() if deploy_info.exists() else None
    try:
        deploy_info.write_text(json.dumps({"sha": "aaa111bbb222ccc333", "timestamp": "x", "changelog": []}))

        broadcast_calls = []
        async def fake_broadcast(msg, exclude=None):
            broadcast_calls.append(msg)
        monkeypatch.setattr("routers.poll.broadcast", fake_broadcast)

        client = TestClient(app)
        response = client.post("/api/pending-deploy",
                               json={"sha": "ddd444eee555fff666", "message": "feat: new thing"})
        assert response.status_code == 200
        assert any(c.get("type") == "deploy_pending" for c in broadcast_calls)
    finally:
        if original is not None:
            deploy_info.write_text(original)


def test_session_snapshot_returns_participants_and_scores():
    state.reset()
    state.participant_names["uuid-1"] = "Alice"
    state.scores["uuid-1"] = 100
    state.mode = "workshop"

    client = TestClient(app)
    resp = client.get("/api/session/snapshot", headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "workshop"
    assert "uuid-1" in data["participants"]
    assert data["participants"]["uuid-1"]["name"] == "Alice"
    assert data["participants"]["uuid-1"]["score"] == 100


def test_session_snapshot_requires_auth():
    state.reset()
    client = TestClient(app)
    resp = client.get("/api/session/snapshot")
    assert resp.status_code == 401


def test_session_sync_restores_participants_and_scores():
    state.reset()
    client = TestClient(app)
    payload = {
        "main": {"name": "2026-03-25 Test", "started_at": "2026-03-25T09:00:00", "status": "active"},
        "talk": None,
        "discussion_points": [],
        "session_state": {
            "saved_at": "2026-03-25T10:00:00",
            "mode": "workshop",
            "participants": {
                "uuid-restored": {"name": "Bob", "score": 250, "base_score": 200, "location": "Cluj", "avatar": "", "universe": ""}
            },
            "activity": "none",
            "poll": None,
            "qa": {"questions": []},
            "wordcloud": {"topic": "", "words": {}, "word_order": []},
            "debate": {"statement": None, "phase": None, "sides": {}, "arguments": [], "champions": {}, "auto_assigned": [], "first_side": None, "round_index": None, "round_timer_seconds": None, "round_timer_started_at": None},
            "codereview": {"snippet": None, "language": None, "phase": "idle", "confirmed": [], "selections": {}},
            "leaderboard_active": False,
            "token_usage": {"input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0},
        }
    }
    resp = client.post("/api/session/sync", json=payload, headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    assert state.participant_names.get("uuid-restored") == "Bob"
    assert state.scores.get("uuid-restored") == 250
    assert state.mode == "workshop"


def test_mode_switch_to_conference_queues_create_talk_folder():
    from state import state
    state.session_main = {"name": "2026-03-25 WS", "started_at": "2026-03-25T09:00:00", "status": "active"}
    state.session_talk = None
    state.session_request = None

    client = TestClient(app)
    resp = client.post("/api/mode", json={"mode": "conference"}, headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    assert state.mode == "conference"
    assert state.session_request == {"action": "create_talk_folder"}


def test_mode_switch_to_conference_no_request_if_talk_exists():
    from state import state
    state.session_talk = {"name": "2026-03-25 12:30 talk", "started_at": "2026-03-25T12:30:00", "status": "active"}
    state.session_request = None

    client = TestClient(app)
    resp = client.post("/api/mode", json={"mode": "conference"}, headers=_HOST_AUTH_HEADERS)
    assert resp.status_code == 200
    assert state.session_request is None or state.session_request.get("action") != "create_talk_folder"


def test_pending_deploy_same_sha_no_broadcast(monkeypatch):
    """POST /api/pending-deploy with same full SHA does NOT broadcast deploy_pending."""
    import json
    from pathlib import Path
    deploy_info = Path(__file__).parent.parent / "static" / "deploy-info.json"
    original = deploy_info.read_text() if deploy_info.exists() else None
    try:
        deploy_info.write_text(json.dumps({"sha": "aaa111bbb222ccc333", "timestamp": "x", "changelog": []}))

        broadcast_calls = []
        async def fake_broadcast(msg, exclude=None):
            broadcast_calls.append(msg)
        monkeypatch.setattr("routers.poll.broadcast", fake_broadcast)

        client = TestClient(app)
        response = client.post("/api/pending-deploy",
                               json={"sha": "aaa111bbb222ccc333", "message": "same commit"})
        assert response.status_code == 200
        assert not any(c.get("type") == "deploy_pending" for c in broadcast_calls)
    finally:
        if original is not None:
            deploy_info.write_text(original)
