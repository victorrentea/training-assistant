"""Tests for deleting a participant from a live session.

Two layers: the pure purge (does it really empty every store the participant
touched?) and the endpoint's guards (proxy, unknown id, still-active).
"""
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from daemon.codereview.state import codereview_state
from daemon.debate.state import debate_state
from daemon.misc.state import misc_state
from daemon.participant.purge import ACTIVE_WINDOW_MS, is_active, purge_participant
from daemon.participant.router import host_router
from daemon.participant.state import participant_state
from daemon.poll.state import PollData, poll_state
from daemon.qa.state import qa_state
from daemon.quiz.state import quiz_state
from daemon.scores import scores as daemon_scores

GHOST = "ghost-uuid"
KEEPER = "keeper-uuid"


@pytest.fixture(autouse=True)
def clean_state():
    _reset_all()
    yield
    _reset_all()


def _reset_all():
    participant_state.reset()
    daemon_scores.reset()
    quiz_state.clear()
    poll_state.reset()
    qa_state.questions.clear()
    debate_state.reset()
    codereview_state.selections.clear()
    misc_state.paste_texts.clear()
    misc_state.uploaded_files.clear()
    misc_state.bug_reports_sent.clear()


def _seed_ghost_everywhere():
    """Give GHOST an entry in every per-participant store, plus a KEEPER to
    prove the purge is surgical rather than a session wipe."""
    ps = participant_state
    for pid, name in ((GHOST, "Samwise"), (KEEPER, "Real Person")):
        ps.participant_names[pid] = name
        ps.participant_avatars[pid] = f"{name}.png"
        ps.locations[pid] = "Bucharest"
        ps.location_timezones[pid] = "Europe/Bucharest"
        ps.location_countries[pid] = "RO"
        ps.engagement[pid] = {"slides": {"seconds": 10, "visits": 1, "clicks": 0}}
        ps.last_view[pid] = "slides"
        daemon_scores.scores[pid] = 7
        daemon_scores.base_scores[pid] = 3
        quiz_state.votes[pid] = {"option_indices": [0], "voted_at": "now"}
        quiz_state.awarded_points[pid] = 5
        poll_state.votes[pid] = {"option_indices": [1], "voted_at": "now"}
        codereview_state.selections[pid] = {3, 4}
        misc_state.paste_texts[pid] = [{"id": "p1", "text": "hi"}]
        misc_state.uploaded_files[pid] = [{"id": "f1", "filename": "x.txt"}]
        misc_state.bug_reports_sent[pid] = [time.time()]
        debate_state.sides[pid] = "for"
    ps.anonymous_pids.add(GHOST)
    ps.online_participants.add(KEEPER)
    debate_state.auto_assigned.add(GHOST)
    debate_state.champions["for"] = GHOST
    debate_state.arguments = [
        {"id": "a1", "author_uuid": GHOST, "side": "for", "text": "mine", "upvoters": {KEEPER}},
        {"id": "a2", "author_uuid": KEEPER, "side": "for", "text": "theirs", "upvoters": {GHOST}},
    ]
    qa_state.questions = {
        "q1": {"id": "q1", "text": "mine", "author": GHOST, "upvoters": {KEEPER}, "answered": False,
               "timestamp": 1.0},
        "q2": {"id": "q2", "text": "theirs", "author": KEEPER, "upvoters": {GHOST}, "answered": False,
               "timestamp": 2.0},
    }


class TestPurgeParticipant:
    def test_removes_ghost_from_every_store(self):
        _seed_ghost_everywhere()
        purge_participant(GHOST)

        ps = participant_state
        assert GHOST not in ps.participant_names
        assert GHOST not in ps.participant_avatars
        assert GHOST not in ps.anonymous_pids
        assert GHOST not in ps.locations
        assert GHOST not in ps.location_timezones
        assert GHOST not in ps.location_countries
        assert GHOST not in ps.engagement
        assert GHOST not in ps.last_view
        assert GHOST not in daemon_scores.scores
        assert GHOST not in daemon_scores.base_scores
        assert GHOST not in quiz_state.votes
        assert GHOST not in quiz_state.awarded_points
        assert GHOST not in poll_state.votes
        assert GHOST not in codereview_state.selections
        assert GHOST not in misc_state.paste_texts
        assert GHOST not in misc_state.uploaded_files
        assert GHOST not in misc_state.bug_reports_sent
        assert GHOST not in debate_state.sides
        assert GHOST not in debate_state.auto_assigned
        assert GHOST not in debate_state.champions.values()

    def test_own_content_deleted_and_upvotes_withdrawn(self):
        _seed_ghost_everywhere()
        purge_participant(GHOST)

        # The ghost's own question/argument are gone, the other author's stay…
        assert set(qa_state.questions) == {"q2"}
        assert [a["id"] for a in debate_state.arguments] == ["a2"]
        # …minus the ghost's upvote on them.
        assert qa_state.questions["q2"]["upvoters"] == set()
        assert debate_state.arguments[0]["upvoters"] == set()

    def test_other_participants_untouched(self):
        _seed_ghost_everywhere()
        purge_participant(GHOST)

        assert participant_state.participant_names[KEEPER] == "Real Person"
        assert daemon_scores.scores[KEEPER] == 7
        assert quiz_state.votes[KEEPER]["option_indices"] == [0]
        assert poll_state.votes[KEEPER]["option_indices"] == [1]
        assert codereview_state.selections[KEEPER] == {3, 4}
        assert debate_state.sides[KEEPER] == "for"

    def test_report_lists_what_was_removed(self):
        _seed_ghost_everywhere()
        report = purge_participant(GHOST)

        assert report.participant_id == GHOST
        assert report.name == "Samwise"
        assert report.removed["name"] == 1
        assert report.removed["qa_question"] == 1
        assert report.removed["qa_upvote"] == 1
        assert report.removed["debate_argument"] == 1
        assert report.removed["debate_champion"] == 1
        # Only stores that actually held something are reported.
        assert all(count > 0 for count in report.removed.values())

    def test_stale_vote_tally_is_recomputed(self):
        # The tally is cached; a purge that forgot to invalidate it would keep
        # counting the deleted participant's vote.
        quiz_state.quiz = {"id": "q", "question": "?", "options": ["a", "b"], "multi": False}
        quiz_state.votes[GHOST] = {"option_indices": [0], "voted_at": "now"}
        participant_state.participant_names[GHOST] = "Samwise"
        assert quiz_state.vote_counts() == [1, 0]

        purge_participant(GHOST)
        assert quiz_state.vote_counts() == [0, 0]

    def test_poll_tally_is_recomputed(self):
        poll_state.data = PollData(question="?", options=["a", "b"], multi=False, public=True)
        poll_state.votes[GHOST] = {"option_indices": [1], "voted_at": "now"}
        participant_state.participant_names[GHOST] = "Samwise"
        assert poll_state.vote_counts() == [0, 1]

        purge_participant(GHOST)
        assert poll_state.vote_counts() == [0, 0]

    def test_names_broadcast_gate_is_reopened(self):
        # The roster broadcast is skipped when the name multiset is unchanged
        # since the last publish. A purge must clear that memo, or the removal
        # never reaches the participants.
        participant_state.participant_names[GHOST] = "Samwise"
        participant_state.last_broadcast_names = ["Samwise"]

        purge_participant(GHOST)
        assert participant_state.last_broadcast_names is None

    def test_purging_an_empty_participant_reports_nothing(self):
        participant_state.participant_names[GHOST] = "Samwise"
        report = purge_participant(GHOST)
        assert report.removed == {"name": 1}


class TestIsActive:
    def test_connected_participant_is_active(self):
        participant_state.online_participants.add(GHOST)
        assert is_active(GHOST) is True

    def test_recent_heartbeat_is_active(self):
        now = time.time() * 1000.0
        participant_state.last_active_at[GHOST] = now - 1_000
        assert is_active(GHOST, now_ms=now) is True

    def test_old_heartbeat_is_inactive(self):
        now = time.time() * 1000.0
        participant_state.last_active_at[GHOST] = now - ACTIVE_WINDOW_MS - 1
        assert is_active(GHOST, now_ms=now) is False

    def test_never_seen_is_inactive(self):
        assert is_active(GHOST) is False


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(host_router)
    with patch("daemon.participant.router._notify_host_participant_list", new=AsyncMock()), \
         patch("daemon.participant.router._publish_scores_after_purge", new=AsyncMock()):
        yield TestClient(app)


class TestDeleteParticipantEndpoint:
    def test_deletes_inactive_participant(self, client):
        _seed_ghost_everywhere()
        r = client.delete(f"/api/sid1/host/participants/{GHOST}")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Samwise"
        assert body["removed"]["name"] == 1
        assert GHOST not in participant_state.participant_names

    def test_unknown_participant_is_404(self, client):
        r = client.delete("/api/sid1/host/participants/nobody")
        assert r.status_code == 404

    def test_active_participant_is_409(self, client):
        participant_state.participant_names[GHOST] = "Samwise"
        participant_state.online_participants.add(GHOST)
        r = client.delete(f"/api/sid1/host/participants/{GHOST}")
        assert r.status_code == 409
        assert r.json()["name"] == "Samwise"
        # Refused means untouched — not half-deleted.
        assert GHOST in participant_state.participant_names

    def test_active_participant_can_be_forced(self, client):
        participant_state.participant_names[GHOST] = "Samwise"
        participant_state.online_participants.add(GHOST)
        r = client.delete(f"/api/sid1/host/participants/{GHOST}?force=true")
        assert r.status_code == 200
        assert r.json()["was_active"] is True
        assert GHOST not in participant_state.participant_names

    def test_proxied_request_is_403(self, client):
        # Same guard as the trainer-claim endpoint: a destructive host action
        # must not be reachable from the internet through the Railway relay.
        participant_state.participant_names[GHOST] = "Samwise"
        r = client.delete(
            f"/api/sid1/host/participants/{GHOST}",
            headers={"x-railway-proxied": "1"},
        )
        assert r.status_code == 403
        assert GHOST in participant_state.participant_names
