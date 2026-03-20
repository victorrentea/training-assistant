import logging
import random
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_host_auth
from messaging import broadcast, broadcast_state, participant_ids
from state import state, ActivityType

def get_debate_sub_phases(first_side: str) -> list[dict]:
    """Generate 4 timed sub-phases based on which side speaks first."""
    other = "against" if first_side == "for" else "for"
    fl, ol = first_side.upper(), other.upper()
    return [
        {"key": f"opening_{first_side}",  "label": f"Opening — {fl}",  "side": first_side, "default_seconds": 120},
        {"key": f"opening_{other}",       "label": f"Opening — {ol}",  "side": other,      "default_seconds": 120},
        {"key": f"rebuttal_{first_side}", "label": f"Rebuttal — {fl}", "side": first_side, "default_seconds": 90},
        {"key": f"rebuttal_{other}",      "label": f"Rebuttal — {ol}", "side": other,      "default_seconds": 90},
    ]

router = APIRouter()
logger = logging.getLogger(__name__)


def auto_assign_remaining(all_pids: list[str], sides: dict[str, str]) -> list[str]:
    """Auto-assign unassigned participants to balance teams.

    Triggers when at least half have picked (assigned * 2 >= total).
    Returns list of newly-assigned participant IDs, or [] if not triggered.
    """
    assigned_count = sum(1 for p in all_pids if p in sides)
    if assigned_count * 2 < len(all_pids) or assigned_count == 0:
        return []

    unassigned = [p for p in all_pids if p not in sides]
    if not unassigned:
        return []

    for_count = sum(1 for s in sides.values() if s == "for")
    against_count = sum(1 for s in sides.values() if s == "against")

    random.shuffle(unassigned)
    newly_assigned = []
    for p in unassigned:
        if for_count <= against_count:
            sides[p] = "for"
            for_count += 1
        else:
            sides[p] = "against"
            against_count += 1
        newly_assigned.append(p)
    return newly_assigned


class DebateLaunch(BaseModel):
    statement: str


class PhaseAdvance(BaseModel):
    phase: str  # "arguments"|"ai_cleanup"|"prep"|"live_debate"|"ended"


@router.post("/api/debate", dependencies=[Depends(require_host_auth)])
async def launch_debate(body: DebateLaunch):
    statement = body.statement.strip()
    if not statement:
        raise HTTPException(400, "Statement cannot be empty")

    # Reset all debate state
    state.debate_statement = statement
    state.debate_phase = "side_selection"
    state.debate_sides = {}
    state.debate_arguments = []
    state.debate_champions = {}
    state.debate_auto_assigned = set()
    state.debate_first_side = None
    state.debate_sub_phase_index = None
    state.debate_sub_timer_seconds = None
    state.debate_sub_timer_started_at = None
    state.current_activity = ActivityType.DEBATE

    logger.info(f"Debate launched: {statement}")
    await broadcast_state()
    return {"ok": True}


@router.post("/api/debate/reset", dependencies=[Depends(require_host_auth)])
async def reset_debate():
    """Reset all debate state back to scratch."""
    state.debate_statement = None
    state.debate_phase = None
    state.debate_sides = {}
    state.debate_arguments = []
    state.debate_champions = {}
    state.debate_auto_assigned = set()
    state.debate_first_side = None
    state.debate_sub_phase_index = None
    state.debate_sub_timer_seconds = None
    state.debate_sub_timer_started_at = None
    state.current_activity = ActivityType.NONE

    logger.info("Debate reset")
    await broadcast_state()
    return {"ok": True}


@router.post("/api/debate/close-selection", dependencies=[Depends(require_host_auth)])
async def close_selection():
    if state.debate_phase != "side_selection":
        raise HTTPException(400, "Not in side_selection phase")

    # Auto-assign any remaining participants to balance sides
    all_pids = participant_ids()
    newly = auto_assign_remaining(all_pids, state.debate_sides)
    if newly:
        state.debate_auto_assigned.update(newly)

    for_count = sum(1 for s in state.debate_sides.values() if s == "for")
    against_count = sum(1 for s in state.debate_sides.values() if s == "against")

    # Advance to arguments phase (atomic)
    state.debate_phase = "arguments"
    logger.info(f"Selection closed: {for_count} FOR, {against_count} AGAINST")
    await broadcast_state()
    return {"ok": True, "for": for_count, "against": against_count}


@router.post("/api/debate/force-assign", dependencies=[Depends(require_host_auth)])
async def force_assign():
    if state.debate_phase != "side_selection":
        raise HTTPException(400, "Not in side_selection phase")

    all_pids = participant_ids()
    unassigned = [p for p in all_pids if p not in state.debate_sides]
    if not unassigned:
        raise HTTPException(400, "No unassigned participants")

    for_count = sum(1 for s in state.debate_sides.values() if s == "for")
    against_count = sum(1 for s in state.debate_sides.values() if s == "against")

    random.shuffle(unassigned)
    for p in unassigned:
        if for_count <= against_count:
            state.debate_sides[p] = "for"
            for_count += 1
        else:
            state.debate_sides[p] = "against"
            against_count += 1
        state.debate_auto_assigned.add(p)

    logger.info(f"Force-assigned {len(unassigned)} participants: {for_count} FOR, {against_count} AGAINST")

    # Auto-advance: all participants now have sides
    state.debate_phase = "arguments"
    logger.info("All participants assigned — auto-advancing to arguments phase")

    await broadcast_state()
    return {"ok": True, "assigned": len(unassigned)}


VALID_PHASES = {"arguments", "ai_cleanup", "prep", "live_debate", "ended"}


@router.post("/api/debate/phase", dependencies=[Depends(require_host_auth)])
async def advance_phase(body: PhaseAdvance):
    if body.phase not in VALID_PHASES:
        raise HTTPException(400, f"Invalid phase: {body.phase}")
    if not state.debate_statement:
        raise HTTPException(400, "No debate active")

    if body.phase == "live_debate":
        state.debate_first_side = None
        state.debate_sub_phase_index = None
        state.debate_sub_timer_seconds = None
        state.debate_sub_timer_started_at = None
    state.debate_phase = body.phase
    logger.info(f"Debate phase → {body.phase}")
    await broadcast_state()
    return {"ok": True, "phase": body.phase}


class FirstSide(BaseModel):
    side: str  # "for" or "against"


@router.post("/api/debate/first-side", dependencies=[Depends(require_host_auth)])
async def set_first_side(body: FirstSide):
    if state.debate_phase != "live_debate":
        raise HTTPException(400, "Not in live_debate phase")
    if body.side not in ("for", "against"):
        raise HTTPException(400, "Side must be 'for' or 'against'")
    state.debate_first_side = body.side
    state.debate_sub_phase_index = None
    logger.info(f"Live debate: {body.side.upper()} goes first")
    await broadcast_state()
    return {"ok": True}


class SubPhaseTimer(BaseModel):
    sub_phase_index: int
    seconds: int


@router.post("/api/debate/sub-phase-timer", dependencies=[Depends(require_host_auth)])
async def start_sub_phase_timer(body: SubPhaseTimer):
    if state.debate_phase != "live_debate":
        raise HTTPException(400, "Not in live_debate phase")
    if not state.debate_first_side:
        raise HTTPException(400, "First side not picked yet")
    sub_phases = get_debate_sub_phases(state.debate_first_side)
    if not 0 <= body.sub_phase_index < len(sub_phases):
        raise HTTPException(400, f"Invalid sub-phase index: {body.sub_phase_index}")
    if body.seconds < 1:
        raise HTTPException(400, "Duration must be at least 1 second")

    started_at = datetime.now(timezone.utc)
    state.debate_sub_phase_index = body.sub_phase_index
    state.debate_sub_timer_seconds = body.seconds
    state.debate_sub_timer_started_at = started_at

    sub = sub_phases[body.sub_phase_index]
    logger.info(f"Sub-phase timer started: {sub['label']} ({body.seconds}s)")

    await broadcast({"type": "debate_timer", "sub_phase_index": body.sub_phase_index, "seconds": body.seconds, "started_at": started_at.isoformat()})
    await broadcast_state()
    return {"ok": True}


@router.post("/api/debate/end-sub-phase", dependencies=[Depends(require_host_auth)])
async def end_sub_phase():
    """End the current sub-phase early."""
    if state.debate_phase != "live_debate":
        raise HTTPException(400, "Not in live_debate phase")
    if state.debate_sub_phase_index is None or state.debate_sub_timer_started_at is None:
        raise HTTPException(400, "No sub-phase timer active")

    ended_index = state.debate_sub_phase_index
    state.debate_sub_timer_seconds = None
    state.debate_sub_timer_started_at = None

    logger.info(f"Sub-phase {ended_index} ended early by host")
    await broadcast({"type": "debate_phase_ended", "sub_phase_index": ended_index})
    await broadcast_state()
    return {"ok": True}


@router.post("/api/debate/end-arguments", dependencies=[Depends(require_host_auth)])
async def end_arguments():
    """End arguments phase — store AI request for daemon pickup."""
    if state.debate_phase != "arguments":
        raise HTTPException(400, "Not in arguments phase")

    # Build the payload the daemon will consume
    for_args = [{"id": a["id"], "text": a["text"]} for a in state.debate_arguments
                if a["side"] == "for" and not a.get("merged_into")]
    against_args = [{"id": a["id"], "text": a["text"]} for a in state.debate_arguments
                    if a["side"] == "against" and not a.get("merged_into")]

    if not for_args and not against_args:
        # No arguments submitted — skip AI cleanup, go straight to prep
        state.debate_phase = "prep"
        logger.info("Arguments ended (none submitted) — skipping AI, advancing to prep")
        await broadcast_state()
        return {"ok": True}

    state.debate_ai_request = {
        "statement": state.debate_statement,
        "for_args": for_args,
        "against_args": against_args,
    }
    state.debate_phase = "ai_cleanup"
    logger.info("Arguments ended — waiting for daemon AI cleanup")
    await broadcast_state()
    return {"ok": True}


@router.get("/api/debate/ai-request", dependencies=[Depends(require_host_auth)])
async def poll_debate_ai_request():
    """Daemon polls this. Returns pending AI request or null, then clears it."""
    req = state.debate_ai_request
    state.debate_ai_request = None
    return {"request": req}


class DebateAiResult(BaseModel):
    merges: list[dict] = []
    cleaned: list[dict] = []
    new_arguments: list[dict] = []


@router.post("/api/debate/ai-result", dependencies=[Depends(require_host_auth)])
async def receive_ai_result(body: DebateAiResult):
    """Daemon posts AI cleanup results. Apply and advance to prep."""
    if state.debate_phase != "ai_cleanup":
        raise HTTPException(400, "Not in ai_cleanup phase")

    # Apply merges
    for merge in body.merges:
        keep_id = merge.get("keep_id")
        for remove_id in merge.get("remove_ids", []):
            for arg in state.debate_arguments:
                if arg["id"] == remove_id:
                    arg["merged_into"] = keep_id
                    kept = next((a for a in state.debate_arguments if a["id"] == keep_id), None)
                    if kept:
                        kept["upvoters"] = kept["upvoters"] | arg["upvoters"]

    # Apply cleaned text
    for cleaned in body.cleaned:
        for arg in state.debate_arguments:
            if arg["id"] == cleaned.get("id"):
                arg["text"] = cleaned["text"]

    # Add new AI arguments
    for new_arg in body.new_arguments:
        state.debate_arguments.append({
            "id": str(uuid_mod.uuid4()),
            "author_uuid": "__ai__",
            "side": new_arg["side"],
            "text": new_arg["text"],
            "upvoters": set(),
            "ai_generated": True,
            "merged_into": None,
        })

    logger.info(f"AI result received: {len(body.merges)} merges, {len(body.new_arguments)} new args")

    state.debate_phase = "prep"
    await broadcast_state()
    return {"ok": True}
