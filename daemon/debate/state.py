"""Debate state cache for daemon.

Owns all debate state. Initial data comes from daemon_state_push on WS connect.
"""
import random
import threading
import uuid as uuid_mod
from datetime import datetime, timezone


class DebateState:
    """Debate state. Mutation methods run on uvicorn's single-threaded
    event loop (no lock needed). sync_from_restore runs on the main thread
    and uses _lock for cross-thread safety.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.statement: str | None = None
        self.phase: str | None = None  # "side_selection"|"arguments"|"ai_cleanup"|"prep"|"live_debate"|"ended"
        self.sides: dict[str, str] = {}  # uuid → "for"|"against"
        self.arguments: list[dict] = []  # [{id, author_uuid, side, text, upvoters: set, ai_generated, merged_into}]
        self.champions: dict[str, str] = {}  # "for"|"against" → uuid
        self.auto_assigned: set[str] = set()
        self.first_side: str | None = None
        self.round_index: int | None = None
        self.round_timer_seconds: int | None = None
        self.round_timer_started_at: datetime | None = None
        self.ai_request: dict | None = None

    def sync_from_restore(self, data: dict):
        """Update from daemon_state_push. Called from main thread."""
        with self._lock:
            payload = data.get("debate")
            if not isinstance(payload, dict):
                payload = {}

            if "statement" in payload or "debate_statement" in data:
                self.statement = (
                    payload.get("statement")
                    if "statement" in payload
                    else data.get("debate_statement")
                )
            if "phase" in payload or "debate_phase" in data:
                self.phase = (
                    payload.get("phase")
                    if "phase" in payload
                    else data.get("debate_phase")
                )
            if "sides" in payload or "debate_sides" in data:
                self.sides.clear()
                sides = payload.get("sides") if "sides" in payload else data.get("debate_sides")
                self.sides.update(sides or {})
            if "arguments" in payload or "debate_arguments" in data:
                self.arguments.clear()
                arguments = (
                    payload.get("arguments")
                    if "arguments" in payload
                    else data.get("debate_arguments")
                ) or []
                for arg in arguments:
                    a = dict(arg)
                    # upvoters comes as list from JSON — convert to set
                    a["upvoters"] = set(a.get("upvoters", []))
                    self.arguments.append(a)
            if "champions" in payload or "debate_champions" in data:
                self.champions.clear()
                champions = (
                    payload.get("champions")
                    if "champions" in payload
                    else data.get("debate_champions")
                )
                self.champions.update(champions or {})
            if "auto_assigned" in payload or "debate_auto_assigned" in data:
                auto_assigned = (
                    payload.get("auto_assigned")
                    if "auto_assigned" in payload
                    else data.get("debate_auto_assigned")
                ) or []
                self.auto_assigned = set(auto_assigned)
            if "first_side" in payload or "debate_first_side" in data:
                self.first_side = (
                    payload.get("first_side")
                    if "first_side" in payload
                    else data.get("debate_first_side")
                )
            if "round_index" in payload or "debate_round_index" in data:
                self.round_index = (
                    payload.get("round_index")
                    if "round_index" in payload
                    else data.get("debate_round_index")
                )
            if "round_timer_seconds" in payload or "debate_round_timer_seconds" in data:
                self.round_timer_seconds = (
                    payload.get("round_timer_seconds")
                    if "round_timer_seconds" in payload
                    else data.get("debate_round_timer_seconds")
                )
            if "round_timer_started_at" in payload or "debate_round_timer_started_at" in data:
                val = (
                    payload.get("round_timer_started_at")
                    if "round_timer_started_at" in payload
                    else data.get("debate_round_timer_started_at")
                )
                if isinstance(val, str):
                    try:
                        self.round_timer_started_at = datetime.fromisoformat(val)
                    except ValueError:
                        self.round_timer_started_at = None
                else:
                    self.round_timer_started_at = val

    def launch(self, statement: str):
        """Reset all fields, set statement, phase=side_selection."""
        self.statement = statement
        self.phase = "side_selection"
        self.sides.clear()
        self.arguments.clear()
        self.champions.clear()
        self.auto_assigned.clear()
        self.first_side = None
        self.round_index = None
        self.round_timer_seconds = None
        self.round_timer_started_at = None
        self.ai_request = None

    def reset(self):
        """Clear everything back to None/empty."""
        self.statement = None
        self.phase = None
        self.sides.clear()
        self.arguments.clear()
        self.champions.clear()
        self.auto_assigned.clear()
        self.first_side = None
        self.round_index = None
        self.round_timer_seconds = None
        self.round_timer_started_at = None
        self.ai_request = None

    def pick_side(self, pid: str, side: str) -> bool:
        """Assign side if valid. Return True if accepted."""
        if self.phase != "side_selection":
            return False
        if side not in ("for", "against"):
            return False
        if pid in self.sides:
            return False
        self.sides[pid] = side
        return True

    def auto_assign_remaining(self, all_pids: list[str]) -> list[str]:
        """Auto-assign unassigned participants to balance teams.

        Triggers when at least half have picked (assigned * 2 >= total).
        Returns list of newly-assigned participant IDs, or [] if not triggered.
        """
        assigned_count = sum(1 for p in all_pids if p in self.sides)
        if assigned_count * 2 < len(all_pids) or assigned_count == 0:
            return []

        unassigned = [p for p in all_pids if p not in self.sides]
        if not unassigned:
            return []

        for_count = sum(1 for s in self.sides.values() if s == "for")
        against_count = sum(1 for s in self.sides.values() if s == "against")

        random.shuffle(unassigned)
        newly_assigned = []
        for p in unassigned:
            if for_count <= against_count:
                self.sides[p] = "for"
                for_count += 1
            else:
                self.sides[p] = "against"
                against_count += 1
            newly_assigned.append(p)
        return newly_assigned

    def close_selection(self, all_pids: list[str]):
        """Auto-assign remaining, then advance to 'arguments' if both sides have members."""
        newly = self.auto_assign_remaining(all_pids)
        if newly:
            self.auto_assigned.update(newly)
        fc, ac = self.side_counts()
        if fc > 0 and ac > 0:
            self.phase = "arguments"

    def force_assign(self, all_pids: list[str]):
        """Force-assign ALL unassigned to balance teams."""
        unassigned = [p for p in all_pids if p not in self.sides]
        if not unassigned:
            return

        for_count = sum(1 for s in self.sides.values() if s == "for")
        against_count = sum(1 for s in self.sides.values() if s == "against")

        random.shuffle(unassigned)
        for p in unassigned:
            if for_count <= against_count:
                self.sides[p] = "for"
                for_count += 1
            else:
                self.sides[p] = "against"
                against_count += 1
            self.auto_assigned.add(p)

        # Auto-advance if all participants now have sides
        self.phase = "arguments"

    def submit_argument(self, pid: str, text: str) -> dict | None:
        """Create argument dict with uuid4 id, return it. Only if phase==arguments and pid in sides."""
        if self.phase != "arguments":
            return None
        if pid not in self.sides:
            return None
        text = text.strip()
        if not text or len(text) > 280:
            return None
        arg = {
            "id": str(uuid_mod.uuid4()),
            "author_uuid": pid,
            "side": self.sides[pid],
            "text": text,
            "upvoters": set(),
            "ai_generated": False,
            "merged_into": None,
        }
        self.arguments.append(arg)
        return arg

    def upvote_argument(self, pid: str, arg_id: str) -> tuple[str, dict] | None:
        """Find argument, check pid not already in upvoters, pid != author.
        Add to upvoters. Return (author_uuid, arg) for scoring."""
        arg = next((a for a in self.arguments if a["id"] == arg_id), None)
        if arg is None:
            return None
        if pid in arg["upvoters"]:
            return None
        if arg["author_uuid"] == pid:
            return None
        arg["upvoters"].add(pid)
        return (arg["author_uuid"], arg)

    def volunteer_champion(self, pid: str) -> str | None:
        """If phase==prep and pid in sides and their side doesn't have a champion yet,
        set champion. Return the side string for scoring."""
        if self.phase != "prep":
            return None
        if pid not in self.sides:
            return None
        my_side = self.sides[pid]
        if my_side in self.champions:
            return None
        self.champions[my_side] = pid
        return my_side

    def advance_phase(self, phase: str):
        """Set self.phase = phase."""
        self.phase = phase

    def set_first_side(self, side: str):
        """Set self.first_side = side."""
        self.first_side = side

    def start_round(self, index: int, seconds: int):
        """Set round_index, round_timer_seconds, round_timer_started_at=now(UTC)."""
        self.round_index = index
        self.round_timer_seconds = seconds
        self.round_timer_started_at = datetime.now(timezone.utc)

    def end_round(self):
        """Set round_timer_started_at=None, round_timer_seconds=None."""
        self.round_timer_started_at = None
        self.round_timer_seconds = None

    def end_arguments(self) -> dict:
        """Build AI request payload. Set phase=ai_cleanup. Return the payload."""
        for_args = [{"id": a["id"], "text": a["text"]} for a in self.arguments
                    if a["side"] == "for" and not a.get("merged_into")]
        against_args = [{"id": a["id"], "text": a["text"]} for a in self.arguments
                        if a["side"] == "against" and not a.get("merged_into")]

        payload = {
            "statement": self.statement,
            "for_args": for_args,
            "against_args": against_args,
        }
        self.ai_request = payload
        self.phase = "ai_cleanup"
        return payload

    def apply_ai_result(self, merges: list, cleaned: list, new_arguments: list):
        """Apply AI cleanup result. Exact logic from features/ws/router.py:154-192."""
        # Apply merges
        for merge in merges:
            keep_id = merge.get("keep_id")
            for remove_id in merge.get("remove_ids", []):
                for arg in self.arguments:
                    if arg["id"] == remove_id:
                        arg["merged_into"] = keep_id
                        kept = next((a for a in self.arguments if a["id"] == keep_id), None)
                        if kept:
                            kept["upvoters"] = kept["upvoters"] | arg["upvoters"]

        # Apply cleaned text
        for c in cleaned:
            for arg in self.arguments:
                if arg["id"] == c.get("id"):
                    arg["text"] = c["text"]

        # Add new AI arguments
        for new_arg in new_arguments:
            self.arguments.append({
                "id": str(uuid_mod.uuid4()),
                "author_uuid": "__ai__",
                "side": new_arg["side"],
                "text": new_arg["text"],
                "upvoters": set(),
                "ai_generated": True,
                "merged_into": None,
            })

        self.phase = "prep"

    def side_counts(self) -> tuple[int, int]:
        """Return (for_count, against_count)."""
        for_count = sum(1 for s in self.sides.values() if s == "for")
        against_count = sum(1 for s in self.sides.values() if s == "against")
        return (for_count, against_count)

    def snapshot(self) -> dict:
        """Return full serializable state. Convert sets to sorted lists, datetime to isoformat."""
        return {
            "statement": self.statement,
            "phase": self.phase,
            "sides": dict(self.sides),
            "arguments": [
                {
                    **a,
                    "upvoters": sorted(a["upvoters"]),
                }
                for a in self.arguments
            ],
            "champions": dict(self.champions),
            "auto_assigned": sorted(self.auto_assigned),
            "first_side": self.first_side,
            "round_index": self.round_index,
            "round_timer_seconds": self.round_timer_seconds,
            "round_timer_started_at": self.round_timer_started_at.isoformat() if self.round_timer_started_at else None,
        }


# Module-level singleton
debate_state = DebateState()
