"""Daemon debate router — participant + host endpoints."""
import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from daemon.debate.state import debate_state
from daemon.participant.state import participant_state
from daemon.scores import scores
from daemon.ws_publish import broadcast, broadcast_event
from daemon.ws_messages import (
    ActivityUpdatedMsg,
    DebateUpdatedMsg,
    DebateTimerMsg,
    DebateRoundEndedMsg,
    ScoresUpdatedMsg,
)

logger = logging.getLogger(__name__)


# ── Pydantic models ──

class OkResponse(BaseModel):
    ok: bool = True

class OkPhaseResponse(BaseModel):
    ok: bool = True
    phase: str

class PickSideRequest(BaseModel):
    side: str

class ArgumentRequest(BaseModel):
    text: str

class UpvoteRequest(BaseModel):
    argument_id: str

class LaunchDebateRequest(BaseModel):
    statement: str

class AdvancePhaseRequest(BaseModel):
    phase: str

class SetFirstSideRequest(BaseModel):
    side: str

class RoundTimerRequest(BaseModel):
    round_index: int
    seconds: int

class AiResultRequest(BaseModel):
    merges: list = []
    cleaned: list = []
    new_arguments: list = []


# ── Participant router (proxied via Railway) ──

participant_router = APIRouter(prefix="/api/participant/debate", tags=["debate"])


@participant_router.post("/pick-side")
async def pick_side(request: Request, body: PickSideRequest):
    """Participant picks a side (for/against)."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    # Activity gate
    if participant_state.current_activity != "debate":
        return JSONResponse({"error": "Debate not active"}, status_code=409)

    if not debate_state.pick_side(pid, body.side):
        return JSONResponse({"error": "Cannot pick side"}, status_code=409)

    # Auto-assign remaining when at least half have picked
    all_pids = list(participant_state.participant_names.keys())
    newly = debate_state.auto_assign_remaining(all_pids)
    if newly:
        debate_state.auto_assigned.update(newly)

    # Auto-advance if all assigned and both sides have members
    if all(p in debate_state.sides for p in all_pids):
        fc, ac = debate_state.side_counts()
        if fc > 0 and ac > 0:
            debate_state.advance_phase("arguments")

    request.state.write_back_events = [
        broadcast_event(DebateUpdatedMsg(**debate_state.snapshot())),
    ]
    return OkResponse()


@participant_router.post("/argument")
async def submit_argument(request: Request, body: ArgumentRequest):
    """Participant submits a debate argument."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    # Activity gate
    if participant_state.current_activity != "debate":
        return JSONResponse({"error": "Debate not active"}, status_code=409)

    text = body.text.strip()

    arg = debate_state.submit_argument(pid, text)
    if arg is None:
        return JSONResponse({"error": "Cannot submit argument"}, status_code=409)

    scores.add_score(pid, 100)

    request.state.write_back_events = [
        broadcast_event(DebateUpdatedMsg(**debate_state.snapshot())),
        broadcast_event(ScoresUpdatedMsg(scores=scores.snapshot())),
    ]
    return OkResponse()


@participant_router.post("/upvote")
async def upvote_argument(request: Request, body: UpvoteRequest):
    """Participant upvotes a debate argument."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    # Activity gate
    if participant_state.current_activity != "debate":
        return JSONResponse({"error": "Debate not active"}, status_code=409)

    result = debate_state.upvote_argument(pid, body.argument_id)
    if result is None:
        return JSONResponse({"error": "Cannot upvote"}, status_code=409)

    author_uuid, arg = result
    if author_uuid != "__ai__":
        scores.add_score(author_uuid, 50)
    scores.add_score(pid, 25)

    request.state.write_back_events = [
        broadcast_event(DebateUpdatedMsg(**debate_state.snapshot())),
        broadcast_event(ScoresUpdatedMsg(scores=scores.snapshot())),
    ]
    return OkResponse()


@participant_router.post("/volunteer")
async def volunteer_champion(request: Request):
    """Participant volunteers as champion for their side."""
    pid = request.headers.get("x-participant-id")
    if not pid:
        return JSONResponse({"error": "Missing X-Participant-ID"}, status_code=400)

    # Activity gate
    if participant_state.current_activity != "debate":
        return JSONResponse({"error": "Debate not active"}, status_code=409)

    side = debate_state.volunteer_champion(pid)
    if side is None:
        return JSONResponse({"error": "Cannot volunteer as champion"}, status_code=409)

    scores.add_score(pid, 2500)

    request.state.write_back_events = [
        broadcast_event(DebateUpdatedMsg(**debate_state.snapshot())),
        broadcast_event(ScoresUpdatedMsg(scores=scores.snapshot())),
    ]
    return OkResponse()


# ── Host router (called directly on daemon localhost) ──
# NOTE: Host JS calls API('/debate') which expands to /api/{session_id}/debate.

host_router = APIRouter(prefix="/api/{session_id}/host/debate", tags=["debate"])

VALID_PHASES = {"arguments", "ai_cleanup", "prep", "live_debate", "ended"}


@host_router.post("")
async def launch_debate(body: LaunchDebateRequest):
    """Host launches a debate with a statement."""
    statement = body.statement.strip()
    if not statement:
        return JSONResponse({"error": "Statement cannot be empty"}, status_code=400)

    participant_state.current_activity = "debate"
    debate_state.launch(statement)

    broadcast(DebateUpdatedMsg(**debate_state.snapshot()))
    broadcast(ActivityUpdatedMsg(current_activity="debate"))
    return OkResponse()


@host_router.post("/reset")
async def reset_debate():
    """Host resets all debate state."""
    debate_state.reset()
    participant_state.current_activity = "none"

    broadcast(DebateUpdatedMsg(**debate_state.snapshot()))
    broadcast(ActivityUpdatedMsg(current_activity="none"))
    return OkResponse()


@host_router.post("/close-selection")
async def close_selection():
    """Host closes side selection; auto-assigns remaining participants."""
    all_pids = list(participant_state.participant_names.keys())
    debate_state.close_selection(all_pids)

    broadcast(DebateUpdatedMsg(**debate_state.snapshot()))
    return OkResponse()


@host_router.post("/force-assign")
async def force_assign():
    """Host force-assigns all unassigned participants."""
    all_pids = list(participant_state.participant_names.keys())
    debate_state.force_assign(all_pids)

    broadcast(DebateUpdatedMsg(**debate_state.snapshot()))
    return OkResponse()


@host_router.post("/phase")
async def advance_phase(body: AdvancePhaseRequest):
    """Host advances the debate to a specific phase."""
    if body.phase not in VALID_PHASES:
        return JSONResponse({"error": f"Invalid phase: {body.phase}"}, status_code=400)

    debate_state.advance_phase(body.phase)
    broadcast(DebateUpdatedMsg(**debate_state.snapshot()))
    return OkPhaseResponse(phase=body.phase)


@host_router.post("/first-side")
async def set_first_side(body: SetFirstSideRequest):
    """Host picks which side speaks first in live debate."""
    if body.side not in ("for", "against"):
        return JSONResponse({"error": "Side must be 'for' or 'against'"}, status_code=400)

    debate_state.set_first_side(body.side)
    broadcast(DebateUpdatedMsg(**debate_state.snapshot()))
    return OkResponse()


@host_router.post("/round-timer")
async def start_round_timer(body: RoundTimerRequest):
    """Host starts a timed round."""
    debate_state.start_round(body.round_index, body.seconds)

    started_at = debate_state.round_timer_started_at.isoformat() if debate_state.round_timer_started_at else None
    broadcast(DebateTimerMsg(round_index=body.round_index, seconds=body.seconds, started_at=started_at))
    broadcast(DebateUpdatedMsg(**debate_state.snapshot()))
    return OkResponse()


@host_router.post("/end-round")
async def end_round():
    """Host ends the current round early."""
    ended_index = debate_state.round_index
    debate_state.end_round()

    broadcast(DebateRoundEndedMsg())
    broadcast(DebateUpdatedMsg(**debate_state.snapshot()))
    return OkResponse()


@host_router.post("/end-arguments")
async def end_arguments():
    """Host ends arguments phase; triggers AI cleanup in background."""
    if debate_state.phase != "arguments":
        return JSONResponse({"error": "Not in arguments phase"}, status_code=409)

    ai_request = debate_state.end_arguments()

    # No arguments submitted — already advanced to prep
    if not ai_request.get("for_args") and not ai_request.get("against_args"):
        debate_state.advance_phase("prep")
        broadcast(DebateUpdatedMsg(**debate_state.snapshot()))
        return OkResponse()

    # Run AI cleanup in background
    async def _run_ai_cleanup(req: dict):
        try:
            from daemon.debate.ai_cleanup import run_debate_ai_cleanup
            from daemon.config import config_from_env
            cfg = config_from_env()
            result = await asyncio.to_thread(run_debate_ai_cleanup, req, cfg.api_key, cfg.model)
            debate_state.apply_ai_result(
                result.get("merges", []),
                result.get("cleaned", []),
                result.get("new_arguments", []),
            )
        except Exception:
            logger.exception("Debate AI cleanup failed — advancing to prep with empty result")
            debate_state.apply_ai_result([], [], [])
        broadcast(DebateUpdatedMsg(**debate_state.snapshot()))

    asyncio.create_task(_run_ai_cleanup(ai_request))

    # Return immediately — broadcast with ai_cleanup phase
    broadcast(DebateUpdatedMsg(**debate_state.snapshot()))
    return OkResponse()


@host_router.post("/ai-result")
async def receive_ai_result(body: AiResultRequest):
    """Manual/skip AI result — host posts AI cleanup results directly."""
    debate_state.apply_ai_result(body.merges, body.cleaned, body.new_arguments)
    broadcast(DebateUpdatedMsg(**debate_state.snapshot()))
    return OkResponse()
