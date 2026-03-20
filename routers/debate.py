import json
import logging
import random
import uuid as uuid_mod
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_host_auth
from messaging import broadcast_state, participant_ids
from state import state, ActivityType

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

    state.debate_phase = body.phase
    logger.info(f"Debate phase → {body.phase}")
    await broadcast_state()
    return {"ok": True, "phase": body.phase}


@router.post("/api/debate/end-arguments", dependencies=[Depends(require_host_auth)])
async def end_arguments():
    """End arguments phase, run AI cleanup, then advance to prep."""
    if state.debate_phase != "arguments":
        raise HTTPException(400, "Not in arguments phase")

    # Transition to ai_cleanup (visible to participants as "AI is reviewing…")
    state.debate_phase = "ai_cleanup"
    logger.info("Arguments ended — running AI cleanup")
    await broadcast_state()

    # Run AI cleanup
    try:
        await _run_ai_cleanup()
    except Exception as e:
        logger.error(f"AI cleanup failed: {e}")
        # Still advance to prep even if AI fails

    # Advance to prep
    state.debate_phase = "prep"
    logger.info("AI cleanup done — advancing to prep")
    await broadcast_state()
    return {"ok": True}


async def _run_ai_cleanup():
    """Run AI cleanup on debate arguments. Raises on failure."""
    if not state.debate_arguments:
        return

    import os
    from anthropic import Anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    # Build prompt
    for_args = [a for a in state.debate_arguments if a["side"] == "for" and not a.get("merged_into")]
    against_args = [a for a in state.debate_arguments if a["side"] == "against" and not a.get("merged_into")]

    prompt = f"""You are helping clean up debate arguments about: "{state.debate_statement}"

FOR arguments:
{chr(10).join(f'- [{a["id"]}] {a["text"]}' for a in for_args)}

AGAINST arguments:
{chr(10).join(f'- [{a["id"]}] {a["text"]}' for a in against_args)}

Tasks:
1. Identify duplicates — return which argument IDs should be merged (keep the better-worded one)
2. For each surviving argument, return a cleaned version (fix typos, make concise, preserve intent)
3. Add 2-4 NEW arguments that participants missed (mark side as "for" or "against")

Return JSON (no markdown fences):
{{
  "merges": [{{"keep_id": "...", "remove_ids": ["..."]}}],
  "cleaned": [{{"id": "...", "text": "cleaned text"}}],
  "new_arguments": [{{"side": "for"|"against", "text": "..."}}]
}}"""

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        result = json.loads(response.content[0].text)
    except (json.JSONDecodeError, IndexError):
        raise HTTPException(500, "AI returned invalid JSON")

    # Apply merges
    for merge in result.get("merges", []):
        keep_id = merge["keep_id"]
        for remove_id in merge.get("remove_ids", []):
            for arg in state.debate_arguments:
                if arg["id"] == remove_id:
                    arg["merged_into"] = keep_id
                    # Transfer upvotes to kept argument
                    kept = next((a for a in state.debate_arguments if a["id"] == keep_id), None)
                    if kept:
                        kept["upvoters"] = kept["upvoters"] | arg["upvoters"]

    # Apply cleaned text
    for cleaned in result.get("cleaned", []):
        for arg in state.debate_arguments:
            if arg["id"] == cleaned["id"]:
                arg["text"] = cleaned["text"]

    # Add new AI arguments
    for new_arg in result.get("new_arguments", []):
        state.debate_arguments.append({
            "id": str(uuid_mod.uuid4()),
            "author_uuid": "__ai__",
            "side": new_arg["side"],
            "text": new_arg["text"],
            "upvoters": set(),
            "ai_generated": True,
            "merged_into": None,
        })

    logger.info(f"AI cleanup done: {len(result.get('merges', []))} merges, {len(result.get('new_arguments', []))} new args")


@router.post("/api/debate/ai-cleanup", dependencies=[Depends(require_host_auth)])
async def ai_cleanup():
    """Legacy endpoint — runs AI cleanup standalone."""
    if state.debate_phase != "ai_cleanup":
        raise HTTPException(400, "Not in ai_cleanup phase")
    await _run_ai_cleanup()
    await broadcast_state()
    return {"ok": True}
