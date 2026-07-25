"""Security + regression tests for the participant-facing broadcast UUID strip.

A participant's identity IS its X-Participant-ID UUID, so leaking another
participant's UUID over a participant-facing frame lets one participant
impersonate another / evade per-UUID rate limits. These tests prove that the
three formerly-UUID-bearing participant frames — ``scores_updated``,
``qa_updated``, ``debate_updated`` — plus the ``GET /api/participant/state``
snapshot are now UUID-free, while every feature still works (own score, own
vote/side, own highlight, correct aggregates), and that the trusted HOST frames
(sent via notify_host) deliberately KEEP their UUIDs.

Two layers:
  • builder-level: exercise the state singletons then serialise the exact wire
    payloads and grep them for UUIDs / assert personalisation booleans;
  • endpoint-level: drive real participant + host HTTP flows and grep EVERY
    participant frame the daemon emits (direct broadcasts via _ws_client + the
    write-back events middleware exposes) plus the /state snapshot.
"""
import json
import re
import uuid as uuid_mod
from contextlib import contextmanager
from unittest.mock import patch

from fastapi import FastAPI, Request
from starlette.testclient import TestClient

from daemon import ws_publish
from daemon.scores import score_token, scores

SESSION = "e2etst"

# uuid4 wire shape: 8-4-4-4-12 hex (dashed). The score token (16 undashed hex)
# and quiz ids (8 undashed hex) deliberately do NOT match this.
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _uuid() -> str:
    return str(uuid_mod.uuid4())


# ── Capture harness ──────────────────────────────────────────────────────────

class _ParticipantRecorder:
    """Stand-in Railway WS client — records every participant broadcast."""

    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)
        return True

    def events(self, msg_type=None):
        out = []
        for m in self.sent:
            if m.get("type") == "broadcast":
                ev = m.get("event", {})
                if msg_type is None or ev.get("type") == msg_type:
                    out.append(ev)
        return out


class _FakeHostWs:
    """Records notify_host frames (the trusted, UUID-bearing host channel)."""

    def __init__(self):
        self.frames = []

    async def send_text(self, payload):
        self.frames.append(json.loads(payload))


@contextmanager
def _env():
    """Fresh state singletons + captured participant/host channels."""
    from daemon.debate.state import debate_state
    from daemon.participant.state import participant_state
    from daemon.qa.state import qa_state
    from daemon.quiz.state import quiz_state
    from daemon.wordcloud.state import wordcloud_state

    def _reset_all():
        participant_state.reset(mode="workshop")
        scores.reset()
        qa_state.clear()
        debate_state.reset()
        quiz_state.quiz = None
        quiz_state.quiz_active = False
        quiz_state.votes.clear()
        quiz_state.awarded_points = {}
        quiz_state.quiz_correct_indices = None
        wordcloud_state.clear()

    _reset_all()
    rec = _ParticipantRecorder()
    host_ws = _FakeHostWs()
    try:
        with patch.object(ws_publish, "_ws_client", rec), \
             patch.object(ws_publish, "_host_wss", {host_ws}):
            yield participant_state, rec, host_ws
    finally:
        _reset_all()


def _build_app() -> FastAPI:
    from daemon.debate.router import host_router as debate_hr
    from daemon.debate.router import participant_router as debate_pr
    from daemon.leaderboard.router import router as lb_router
    from daemon.participant.router import router as participant_router
    from daemon.qa.router import host_router as qa_hr
    from daemon.qa.router import participant_router as qa_pr
    from daemon.quiz.router import host_router as quiz_hr
    from daemon.quiz.router import participant_router as quiz_pr
    from daemon.wordcloud.router import participant_router as wc_pr

    app = FastAPI()

    @app.middleware("http")
    async def _write_back(request: Request, call_next):
        request.state.write_back_events = []
        response = await call_next(request)
        events = getattr(request.state, "write_back_events", [])
        if events:
            response.headers["X-Write-Back-Events"] = json.dumps(events)
        return response

    for r in (participant_router, qa_pr, qa_hr, debate_pr, debate_hr,
              quiz_pr, quiz_hr, wc_pr, lb_router):
        app.include_router(r)
    return app


@contextmanager
def _client():
    with _env() as (ps, rec, host_ws):
        yield TestClient(_build_app()), ps, rec, host_ws


def _hdr(uid):
    return {"X-Participant-ID": uid, "Content-Type": "application/json"}


def _register(client, uid, name):
    return client.post("/api/participant/register", json={"name": name}, headers=_hdr(uid))


def _wb(resp):
    """Participant broadcast events the endpoint returned via the write-back header."""
    raw = resp.headers.get("X-Write-Back-Events")
    if not raw:
        return []
    return [m["event"] for m in json.loads(raw) if m.get("type") == "broadcast"]


def _strip_content_ids(obj):
    """Drop opaque content handles (question/argument ``id``) so the shape-grep
    only judges values that could plausibly be a participant identity.

    A question/argument id IS a uuid4, but it is a content handle — the client
    needs it to upvote/reference the item, it is not in the participant roster,
    and it can never be replayed as an X-Participant-ID to impersonate anyone or
    dodge a per-UUID rate limit. So it is not part of the leak this suite guards.
    """
    if isinstance(obj, dict):
        return {k: _strip_content_ids(v) for k, v in obj.items() if k != "id"}
    if isinstance(obj, list):
        return [_strip_content_ids(x) for x in obj]
    return obj


def _assert_uuid_free(frame, uuids, where):
    blob = json.dumps(frame)
    # (1) The security invariant, mirroring the names-broadcast test: no PARTICIPANT
    # identity UUID may appear ANYWHERE in a participant-facing frame.
    for uid in uuids:
        assert uid not in blob, f"registered participant UUID {uid} leaked in {where}: {frame}"
    # (2) Defence in depth: grep every value for a UUID shape — nothing survives
    # except the exempt opaque content handles (see _strip_content_ids).
    stripped = json.dumps(_strip_content_ids(frame))
    m = _UUID_RE.search(stripped)
    assert m is None, f"unexpected UUID-shaped value {m.group(0)!r} in {where}: {frame}"


# ── Builder-level: the exact wire payloads ───────────────────────────────────

class TestScoresFrameTokenised:
    def test_participant_scores_frame_is_token_keyed_not_uuid(self):
        with _env():
            u1, u2 = _uuid(), _uuid()
            scores.add_score(u1, 300)
            scores.add_score(u2, 150)

            from daemon.ws_messages import ScoresUpdatedMsg
            frame = ScoresUpdatedMsg(scores=scores.snapshot_tokenized()).model_dump()

            _assert_uuid_free(frame, [u1, u2], "scores_updated (participant)")
            # Each participant still resolves its OWN score via its private token.
            assert frame["scores"][score_token(u1)] == 300
            assert frame["scores"][score_token(u2)] == 150
            # Raw UUID keys are gone.
            assert u1 not in frame["scores"] and u2 not in frame["scores"]

    def test_host_scores_frame_keeps_uuid(self):
        with _env():
            u1 = _uuid()
            scores.add_score(u1, 300)
            from daemon.ws_messages import ScoresUpdatedMsg
            host_frame = ScoresUpdatedMsg(scores=scores.snapshot()).model_dump()
            assert host_frame["scores"][u1] == 300  # host is trusted → UUID key kept

    def test_internal_ids_never_tokenised_into_participant_frame(self):
        with _env():
            scores.add_score("__host__", 999)
            scores.add_score("__ai__", 5)
            assert scores.snapshot_tokenized() == {}


class TestQaFrameUuidFree:
    def test_qa_updated_public_frame_is_uuid_free(self):
        with _env():
            from daemon.qa.state import qa_state
            from daemon.ws_messages import QaUpdatedMsg
            author, upvoter = _uuid(), _uuid()
            qid = qa_state.submit(author, "Why streams?")
            qa_state.upvote(qid, upvoter)

            frame = QaUpdatedMsg(questions=qa_state.build_question_list_public()).model_dump()
            _assert_uuid_free(frame, [author, upvoter], "qa_updated (participant)")
            q = frame["questions"][0]
            assert q["upvote_count"] == 1
            assert "author_uuid" not in q and "upvoter_uuids" not in q

    def test_qa_participant_snapshot_resolves_mine_without_uuids(self):
        with _env():
            from daemon.qa.state import qa_state
            author, upvoter = _uuid(), _uuid()
            qid = qa_state.submit(author, "Q")
            qa_state.upvote(qid, upvoter)

            # As the author: is_own True, has_upvoted False.
            mine = qa_state.build_question_list_for_participant(author)[0]
            assert mine["is_own"] is True and mine["has_upvoted"] is False
            # As the upvoter: is_own False, has_upvoted True.
            theirs = qa_state.build_question_list_for_participant(upvoter)[0]
            assert theirs["is_own"] is False and theirs["has_upvoted"] is True
            # Neither personalised view carries a UUID.
            _assert_uuid_free(mine, [author, upvoter], "qa snapshot (author)")
            _assert_uuid_free(theirs, [author, upvoter], "qa snapshot (upvoter)")


class TestDebateFrameUuidFree:
    def _seed(self):
        from daemon.debate.state import debate_state
        a_for, b_against, c = _uuid(), _uuid(), _uuid()
        debate_state.launch("Tabs vs spaces")
        debate_state.pick_side(a_for, "for")
        debate_state.pick_side(b_against, "against")
        debate_state.auto_assigned.add(c)  # c was auto-assigned
        debate_state.sides[c] = "for"
        debate_state.advance_phase("arguments")
        arg = debate_state.submit_argument(a_for, "spaces align")
        debate_state.upvote_argument(b_against, arg["id"])
        debate_state.advance_phase("prep")
        debate_state.volunteer_champion(a_for)
        return a_for, b_against, c, arg

    def test_debate_updated_public_frame_is_uuid_free(self):
        with _env():
            from daemon.debate.state import debate_state
            from daemon.ws_messages import DebateUpdatedMsg
            a_for, b_against, c, arg = self._seed()

            frame = DebateUpdatedMsg(**debate_state.public_snapshot()).model_dump()
            _assert_uuid_free(frame, [a_for, b_against, c], "debate_updated (participant)")
            # Aggregate side counts replace the uuid→side map.
            assert frame["side_counts"] == {"for": 2, "against": 1}
            # champions is side→bool, never side→uuid.
            assert frame["champions"] == {"for": True}
            # arguments carry counts only.
            fa = frame["arguments"][0]
            assert fa["upvote_count"] == 1
            assert "author_uuid" not in fa and "upvoters" not in fa
            # no sides / auto_assigned uuid lists at all
            assert "sides" not in frame and "auto_assigned" not in frame

    def test_debate_participant_snapshot_resolves_mine_without_uuids(self):
        with _env():
            from daemon.participant.router import _build_debate_for_participant
            a_for, b_against, c, arg = self._seed()

            for_view = _build_debate_for_participant(a_for)
            _assert_uuid_free(for_view, [a_for, b_against, c], "debate snapshot (author)")
            assert for_view["my_side"] == "for"
            assert for_view["my_is_champion"] is True
            assert for_view["my_auto_assigned"] is False
            assert for_view["side_counts"] == {"for": 2, "against": 1}
            assert for_view["champions"] == {"for": True}
            my_arg = for_view["arguments"][0]
            assert my_arg["is_own"] is True and my_arg["has_upvoted"] is False

            against_view = _build_debate_for_participant(b_against)
            assert against_view["my_side"] == "against"
            assert against_view["my_is_champion"] is False
            other_arg = against_view["arguments"][0]
            assert other_arg["is_own"] is False and other_arg["has_upvoted"] is True

            auto_view = _build_debate_for_participant(c)
            assert auto_view["my_auto_assigned"] is True


# ── Endpoint-level: grep EVERY participant frame end-to-end ───────────────────

class TestEndToEndNoUuidLeak:
    def _drive_everything(self, client, rec):
        """Exercise register → debate → qa → quiz → leaderboard and collect every
        participant frame the endpoints returned via the write-back header."""
        u1, u2, u3 = _uuid(), _uuid(), _uuid()
        wb_frames = []

        for uid, name in ((u1, "Alice"), (u2, "Bob"), (u3, "Carol")):
            _register(client, uid, name)

        # Debate: launch → pick sides (auto-assigns u3, advances to arguments) →
        # argument → upvote → prep → volunteer.
        base = f"/api/{SESSION}/host/debate"
        client.post(base, json={"statement": "S"})
        wb_frames += _wb(client.post("/api/participant/debate/pick-side",
                                     json={"side": "for"}, headers=_hdr(u1)))
        wb_frames += _wb(client.post("/api/participant/debate/pick-side",
                                     json={"side": "against"}, headers=_hdr(u2)))
        r = client.post("/api/participant/debate/argument",
                        json={"text": "my argument"}, headers=_hdr(u1))
        wb_frames += _wb(r)
        # find the argument id from debate state
        from daemon.debate.state import debate_state
        arg_id = debate_state.arguments[0]["id"]
        wb_frames += _wb(client.post("/api/participant/debate/upvote",
                                     json={"argument_id": arg_id}, headers=_hdr(u2)))
        client.post(f"{base}/phase", json={"phase": "prep"})
        wb_frames += _wb(client.post("/api/participant/debate/volunteer", headers=_hdr(u1)))

        # Q&A: two submits + one upvote.
        wb_frames += _wb(client.post("/api/participant/qa/submit",
                                     json={"text": "Question one?"}, headers=_hdr(u1)))
        r = client.post("/api/participant/qa/submit",
                        json={"text": "Question two?"}, headers=_hdr(u2))
        wb_frames += _wb(r)
        from daemon.qa.state import qa_state
        qid = next(iter(qa_state.questions))
        wb_frames += _wb(client.post("/api/participant/qa/upvote",
                                     json={"question_id": qid}, headers=_hdr(u3)))

        # Quiz: create/open → votes → reveal (broadcasts scores_updated directly).
        qbase = f"/api/{SESSION}/host/quiz"
        client.post(f"{qbase}/manual/submit",
                    json={"question": "2+2?", "options": ["3", "4"], "multi": False})
        wb_frames += _wb(client.post("/api/participant/quiz/vote",
                                     json={"options": [1]}, headers=_hdr(u1)))
        wb_frames += _wb(client.post("/api/participant/quiz/vote",
                                     json={"options": [0]}, headers=_hdr(u2)))
        client.put(f"{qbase}/correct", json={"correct_indices": [1]})

        # Leaderboard reveal + score reset.
        client.post(f"/api/{SESSION}/host/leaderboard/show")
        client.delete(f"/api/{SESSION}/host/scores")

        return (u1, u2, u3), wb_frames

    def test_no_uuid_in_any_participant_frame(self):
        with _client() as (client, ps, rec, host_ws):
            uuids, wb_frames = self._drive_everything(client, rec)

            # Every participant frame: direct broadcasts + write-back events.
            direct = rec.events()
            all_frames = direct + wb_frames
            assert all_frames, "expected participant frames to be emitted"

            # The three formerly-leaky types must all be present AND clean.
            types = {f.get("type") for f in all_frames}
            assert {"scores_updated", "qa_updated", "debate_updated"} <= types, types

            for f in all_frames:
                _assert_uuid_free(f, uuids, f"participant frame {f.get('type')}")

            # The per-connection /state snapshot is participant-facing too.
            snap = client.get("/api/participant/state", headers=_hdr(uuids[0])).json()
            _assert_uuid_free(snap, uuids, "GET /state snapshot")

    def test_host_frames_still_carry_uuid(self):
        """Guard the divergence: the trusted host channel MUST keep UUIDs, proving
        the strip is scoped to participants and didn't blind the host."""
        with _client() as (client, ps, rec, host_ws):
            uuids, _ = self._drive_everything(client, rec)
            host_blob = json.dumps(host_ws.frames)
            # Host received participant_list + qa + scores frames — with UUIDs.
            assert _UUID_RE.search(host_blob), "host frames unexpectedly UUID-free"
            host_types = {f.get("type") for f in host_ws.frames}
            assert "participant_list_updated" in host_types
            # host qa_updated keeps author_uuid
            qa_host = [f for f in host_ws.frames if f.get("type") == "qa_updated"]
            assert qa_host and any(
                "author_uuid" in q for f in qa_host for q in f.get("questions", [])
            )
            # host scores_updated keeps uuid keys
            sc_host = [f for f in host_ws.frames if f.get("type") == "scores_updated"]
            assert sc_host and any(
                any(_UUID_RE.match(k) for k in f["scores"]) for f in sc_host if f["scores"]
            )


class TestFunctionalRegression:
    def test_own_score_resolves_via_snapshot_token(self):
        with _client() as (client, ps, rec, host_ws):
            u1 = _uuid()
            _register(client, u1, "Alice")
            client.post("/api/participant/qa/submit",
                        json={"text": "hi?"}, headers=_hdr(u1))  # +100

            snap = client.get("/api/participant/state", headers=_hdr(u1)).json()
            token = snap["my_score_token"]
            assert snap["my_score"] == 100
            assert token and token != u1
            # The participant resolves its own live score from the token-keyed
            # scores_updated map exactly as the browser does: scores[my_score_token].
            assert scores.snapshot_tokenized()[token] == 100
            assert token == score_token(u1)

    def test_qa_snapshot_is_own_and_has_upvoted_per_viewer(self):
        with _client() as (client, ps, rec, host_ws):
            u1, u2 = _uuid(), _uuid()
            _register(client, u1, "Alice")
            _register(client, u2, "Bob")
            client.post("/api/participant/qa/submit", json={"text": "mine?"}, headers=_hdr(u1))
            from daemon.qa.state import qa_state
            qid = next(iter(qa_state.questions))
            client.post("/api/participant/qa/upvote", json={"question_id": qid}, headers=_hdr(u2))

            s1 = client.get("/api/participant/state", headers=_hdr(u1)).json()
            q1 = s1["qa_questions"][0]
            assert q1["is_own"] is True and q1["has_upvoted"] is False and q1["upvote_count"] == 1

            s2 = client.get("/api/participant/state", headers=_hdr(u2)).json()
            q2 = s2["qa_questions"][0]
            assert q2["is_own"] is False and q2["has_upvoted"] is True

    def test_debate_snapshot_side_counts_and_highlighting(self):
        with _client() as (client, ps, rec, host_ws):
            u1, u2, u3 = _uuid(), _uuid(), _uuid()
            for uid, name in ((u1, "A"), (u2, "B"), (u3, "C")):
                _register(client, uid, name)
            client.post(f"/api/{SESSION}/host/debate", json={"statement": "S"})
            client.post("/api/participant/debate/pick-side", json={"side": "for"}, headers=_hdr(u1))
            client.post("/api/participant/debate/pick-side", json={"side": "against"}, headers=_hdr(u2))
            client.post("/api/participant/debate/argument", json={"text": "arg"}, headers=_hdr(u1))
            from daemon.debate.state import debate_state
            arg_id = debate_state.arguments[0]["id"]
            client.post("/api/participant/debate/upvote", json={"argument_id": arg_id}, headers=_hdr(u2))

            s1 = client.get("/api/participant/state", headers=_hdr(u1)).json()["debate"]
            assert s1["my_side"] == "for"
            assert sum(s1["side_counts"].values()) == 3  # all three assigned
            assert s1["arguments"][0]["is_own"] is True
            assert s1["arguments"][0]["has_upvoted"] is False
            assert s1["arguments"][0]["upvote_count"] == 1

            s2 = client.get("/api/participant/state", headers=_hdr(u2)).json()["debate"]
            assert s2["my_side"] == "against"
            assert s2["arguments"][0]["is_own"] is False
            assert s2["arguments"][0]["has_upvoted"] is True


class TestHostScoreboardNotRegressed:
    """The host also receives the participant broadcast fan-out (token-keyed).
    debate/wordcloud/codereview previously fed the host's scoreboard via that
    fan-out, so once it is token-keyed the host MUST still get a UUID-keyed
    scores frame on its own notify_host channel — otherwise its scoreboard would
    stop updating live during those activities."""

    def _host_uuid_score_frames(self, host_ws):
        frames = [f for f in host_ws.frames if f.get("type") == "scores_updated"]
        return [f for f in frames if any(_UUID_RE.match(k) for k in f.get("scores", {}))]

    def test_debate_argument_pushes_uuid_scores_to_host(self):
        with _client() as (client, ps, rec, host_ws):
            u1, u2, u3 = _uuid(), _uuid(), _uuid()
            for uid in (u1, u2, u3):
                _register(client, uid, "N")
            client.post(f"/api/{SESSION}/host/debate", json={"statement": "S"})
            client.post("/api/participant/debate/pick-side", json={"side": "for"}, headers=_hdr(u1))
            client.post("/api/participant/debate/pick-side", json={"side": "against"}, headers=_hdr(u2))
            host_ws.frames.clear()
            client.post("/api/participant/debate/argument", json={"text": "a"}, headers=_hdr(u1))

            host_scores = self._host_uuid_score_frames(host_ws)
            assert host_scores, "host got no UUID-keyed scores frame after a debate argument"
            assert host_scores[-1]["scores"].get(u1) == 100

    def test_wordcloud_word_pushes_uuid_scores_to_host(self):
        with _client() as (client, ps, rec, host_ws):
            u1 = _uuid()
            _register(client, u1, "N")
            ps.current_activity = "wordcloud"
            host_ws.frames.clear()
            r = client.post("/api/participant/wordcloud/word",
                            json={"word": "kafka"}, headers=_hdr(u1))
            assert r.status_code == 204
            host_scores = self._host_uuid_score_frames(host_ws)
            assert host_scores, "host got no UUID-keyed scores frame after a wordcloud word"
            assert host_scores[-1]["scores"].get(u1) == 200
