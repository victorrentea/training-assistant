"""Erase one participant from the live session state.

Why this exists: a participant is spread across a dozen independent in-memory
stores (roster, scores, votes, Q&A, debate, code review, pastes). Until now the
only way to drop a stray one — a test join, a duplicate tab that took a second
LOTR name, someone who left before the workshop started — was to stop the
daemon, hand-edit `session-state.json` and let it reload. That is a production
restart for a bookkeeping problem, and it is easy to miss a store and leave a
ghost behind (a vote counted for nobody, a question by "Unknown").

This module is the single place that knows the full list of per-participant
stores. Everything here mutates the live singletons in place; the caller is
responsible for the announcements (roster push, scores broadcast, attendees.md).
Persistence needs no explicit call — the main loop's 3-second snapshot flush
notices the changed state and rewrites `session-state.json` on its own.
"""
from __future__ import annotations

import time

from pydantic import BaseModel

# A participant who reported activity within this window counts as active, even
# if the WS roster has not caught up (or was never populated after a restart).
# The participant page heartbeats roughly every 30s while its tab is visible, so
# 90s is "missed three beats" — comfortably beyond a slow network or a tab that
# was briefly backgrounded.
ACTIVE_WINDOW_MS = 90_000


class PurgeReport(BaseModel):
    """What the purge actually removed — one entry per store it touched.

    `removed` maps a store name to the number of entries dropped, and only
    non-zero stores appear, so the report doubles as an explanation of what the
    participant had accumulated. `was_active` records whether the delete had to
    be forced past the liveness guard.
    """
    participant_id: str
    name: str
    removed: dict[str, int] = {}
    was_active: bool = False


def last_active_ms(pid: str) -> float:
    """Epoch-ms of this participant's last activity report (0 if never)."""
    from daemon.participant.state import participant_state

    return float(participant_state.last_active_at.get(pid, 0) or 0)


def is_active(pid: str, *, now_ms: float | None = None) -> bool:
    """True while the participant looks live — connected, or recently heard from.

    Both signals matter: `online_participants` is the WS truth but is empty
    until Railway syncs it, and `last_active_at` survives a reconnect but not a
    daemon restart. Either one is enough to refuse a delete.
    """
    from daemon.participant.state import participant_state

    if pid in participant_state.online_participants:
        return True
    now = time.time() * 1000.0 if now_ms is None else now_ms
    last = last_active_ms(pid)
    return bool(last) and (now - last) < ACTIVE_WINDOW_MS


def is_known(pid: str) -> bool:
    """True if the roster holds this participant id."""
    from daemon.participant.state import participant_state

    return pid in participant_state.participant_names


def purge_participant(pid: str) -> PurgeReport:
    """Remove every trace of `pid` from the live session state.

    Authored content goes with its author: the participant's Q&A questions and
    debate arguments are deleted rather than re-attributed to "Unknown", and
    their upvotes are withdrawn from everyone else's. Aggregates that carry no
    identity (word cloud words, emoji counters) are left alone — nothing in them
    points back at this participant.
    """
    from daemon.codereview.state import codereview_state
    from daemon.debate.state import debate_state
    from daemon.misc.state import misc_state
    from daemon.participant.state import participant_state
    from daemon.poll.state import poll_state
    from daemon.qa.state import qa_state
    from daemon.quiz.state import quiz_state
    from daemon.scores import scores as daemon_scores

    ps = participant_state
    name = ps.participant_names.get(pid, "")
    report = PurgeReport(participant_id=pid, name=name, was_active=is_active(pid))
    counts: dict[str, int] = {}

    def drop(store: str, container, key=None) -> None:
        """Remove `key` (default: pid) from a dict/set, counting the hit."""
        target = pid if key is None else key
        if isinstance(container, set):
            hit = target in container
            container.discard(target)
        else:
            hit = container.pop(target, None) is not None
        if hit:
            counts[store] = counts.get(store, 0) + 1

    # ── Identity & roster ────────────────────────────────────────────────────
    drop("name", ps.participant_names)
    drop("avatar", ps.participant_avatars)
    drop("universe", ps.participant_universes)
    drop("anonymous_flag", ps.anonymous_pids)
    drop("trainer_flag", ps.trainer_pids)
    drop("online", ps.online_participants)
    drop("location", ps.locations)
    drop("location_tz", ps.location_timezones)
    drop("location_country", ps.location_countries)
    drop("engagement", ps.engagement)
    drop("last_active_at", ps.last_active_at)
    drop("last_view", ps.last_view)
    drop("score_cache", ps.scores)
    # The roster changed, so the "names unchanged since last publish" gate in
    # the router must not swallow the next broadcast.
    ps.last_broadcast_names = None

    # ── Scores (authoritative singleton) ─────────────────────────────────────
    drop("score", daemon_scores.scores)
    drop("base_score", daemon_scores.base_scores)

    # ── Votes ────────────────────────────────────────────────────────────────
    drop("quiz_vote", quiz_state.votes)
    drop("quiz_awarded_points", quiz_state.awarded_points)
    quiz_state.invalidate_counts()
    drop("poll_vote", poll_state.votes)
    poll_state.invalidate_counts()

    # ── Q&A: own questions deleted, upvotes withdrawn ────────────────────────
    for qid in [qid for qid, q in qa_state.questions.items() if q.get("author") == pid]:
        drop("qa_question", qa_state.questions, key=qid)
    for question in qa_state.questions.values():
        upvoters = question.get("upvoters")
        if isinstance(upvoters, set):
            drop("qa_upvote", upvoters)

    # ── Debate: side, champion seat, own arguments, upvotes ──────────────────
    drop("debate_side", debate_state.sides)
    drop("debate_auto_assigned", debate_state.auto_assigned)
    for side in [side for side, champ in debate_state.champions.items() if champ == pid]:
        drop("debate_champion", debate_state.champions, key=side)
    own_arguments = [arg for arg in debate_state.arguments if arg.get("author_uuid") == pid]
    for arg in own_arguments:
        debate_state.arguments.remove(arg)
        counts["debate_argument"] = counts.get("debate_argument", 0) + 1
    for arg in debate_state.arguments:
        upvoters = arg.get("upvoters")
        if isinstance(upvoters, set):
            drop("debate_upvote", upvoters)

    # ── Code review, pastes, uploads, rate-limit bookkeeping ─────────────────
    drop("codereview_selection", codereview_state.selections)
    drop("paste_texts", misc_state.paste_texts)
    drop("uploaded_files", misc_state.uploaded_files)
    drop("bug_report_history", misc_state.bug_reports_sent)

    report.removed = counts
    return report
