"""Poll state singleton — daemon owns all poll lifecycle."""
import threading
from datetime import datetime, timezone

_MAX_POINTS = 1000
_MIN_POINTS = 500
_SLOWEST_MULTIPLIER = 3


class PollState:
    def __init__(self):
        self.poll: dict | None = None
        self.poll_active: bool = False
        self.votes: dict[str, dict] = {}  # uuid → {"option_ids": list[str], "voted_at": str ISO}
        self.poll_opened_at: datetime | None = None
        self.poll_correct_ids: list[str] | None = None
        self.poll_timer_seconds: int | None = None
        self.poll_timer_started_at: datetime | None = None
        self._vote_counts_dirty: bool = True
        self._vote_counts_cache: dict | None = None
        self.quiz_md_content: str = ""

    def create_poll(self, question: str, options: list[dict], multi: bool = False,
                    correct_count: int | None = None, source: str | None = None,
                    page: str | None = None) -> dict:
        import uuid as _uuid
        self.poll = {
            "id": _uuid.uuid4().hex[:8],
            "question": question,
            "options": options,
            "multi": multi,
        }
        if correct_count is not None:
            self.poll["correct_count"] = correct_count
        if source:
            self.poll["source"] = source
        if page:
            self.poll["page"] = page
        self.poll_active = False
        self.votes.clear()
        self.poll_correct_ids = None
        self.poll_timer_seconds = None
        self.poll_timer_started_at = None
        self._vote_counts_dirty = True
        return dict(self.poll)

    def open_poll(self, scores_snapshot_fn) -> None:
        self.poll_active = True
        self.poll_opened_at = datetime.now(timezone.utc)
        self.votes.clear()
        self._vote_counts_dirty = True
        scores_snapshot_fn()

    def close_poll(self) -> dict:
        self.poll_active = False
        counts = self.vote_counts()
        total = len(self.votes)
        return {"vote_counts": counts, "total_votes": total}

    def cast_vote(self, pid: str, option_ids: list[str] = None) -> bool:
        if not self.poll or not self.poll_active:
            return False
        if pid in self.votes:
            return False  # votes are final
        if option_ids is None or not isinstance(option_ids, list):
            return False
        valid_ids = [o["id"] for o in self.poll["options"]]
        is_multi = self.poll.get("multi", False)
        if is_multi:
            correct_count = self.poll.get("correct_count")
            max_allowed = correct_count if correct_count else len(valid_ids)
            if (len(option_ids) > max_allowed
                or len(set(option_ids)) != len(option_ids)
                or not all(oid in valid_ids for oid in option_ids)):
                return False
        else:
            if len(option_ids) != 1 or option_ids[0] not in valid_ids:
                return False
        voted_at = datetime.now(timezone.utc).isoformat()
        self.votes[pid] = {"option_ids": option_ids, "voted_at": voted_at}
        self._vote_counts_dirty = True
        return True

    def reveal_correct(self, correct_ids: list[str], scores_obj) -> dict:
        correct_set = set(correct_ids)
        now = datetime.now(timezone.utc)
        opened_at = self.poll_opened_at or now
        all_option_ids = {opt["id"] for opt in self.poll.get("options", [])}
        wrong_set = all_option_ids - correct_set
        multi = self.poll.get("multi", False)

        correct_voters = set()
        for pid, vote in self.votes.items():
            voted = set(vote["option_ids"])
            if multi and correct_set:
                R = len(voted & correct_set)
                W = len(voted & wrong_set)
                if max(0.0, (R - W) / len(correct_set)) > 0:
                    correct_voters.add(pid)
            else:
                if voted & correct_set:
                    correct_voters.add(pid)

        def _elapsed(pid: str) -> float:
            voted_at_str = self.votes[pid]["voted_at"]
            try:
                voted_at = datetime.fromisoformat(voted_at_str)
                return max(0.0, (voted_at - opened_at).total_seconds())
            except Exception:
                return 0.0

        elapsed_times = [_elapsed(p) for p in correct_voters]
        min_time = min(elapsed_times) if elapsed_times else 0.0

        for pid, vote in self.votes.items():
            voted = set(vote["option_ids"])
            if multi and correct_set:
                R = len(voted & correct_set)
                W = len(voted & wrong_set)
                C = len(correct_set)
                ratio = max(0.0, (R - W) / C)
                if ratio == 0:
                    continue
            else:
                if not (voted & correct_set):
                    continue
                ratio = 1.0
            elapsed = _elapsed(pid)
            speed_window = min_time * (_SLOWEST_MULTIPLIER - 1)
            if speed_window > 0:
                decay = min(1.0, (elapsed - min_time) / speed_window)
            else:
                decay = 0.0
            speed_pts = round(_MAX_POINTS - (_MAX_POINTS - _MIN_POINTS) * decay)
            pts = round(speed_pts * ratio)
            if pts > 0:
                scores_obj.add_score(pid, pts)

        self.poll_correct_ids = list(correct_set)
        self._append_to_quiz_md(correct_set)
        return {
            "correct_ids": list(correct_set),
            "scores": scores_obj.snapshot(),
            "votes": {pid: v["option_ids"] for pid, v in self.votes.items()},
        }

    def start_timer(self, seconds: int) -> dict:
        self.poll_timer_seconds = seconds
        self.poll_timer_started_at = datetime.now(timezone.utc)
        return {
            "seconds": seconds,
            "started_at": self.poll_timer_started_at.isoformat(),
        }

    def clear(self) -> None:
        self.poll = None
        self.poll_active = False
        self.votes.clear()
        self.poll_opened_at = None
        self.poll_correct_ids = None
        self.poll_timer_seconds = None
        self.poll_timer_started_at = None
        self._vote_counts_dirty = True

    def vote_counts(self) -> dict:
        if not self._vote_counts_dirty and self._vote_counts_cache is not None:
            return self._vote_counts_cache
        counts: dict[str, int] = {}
        for vote in self.votes.values():
            for oid in vote["option_ids"]:
                counts[oid] = counts.get(oid, 0) + 1
        self._vote_counts_cache = counts
        self._vote_counts_dirty = False
        return counts

    def _append_to_quiz_md(self, correct_set: set[str]):
        if not self.poll:
            return
        lines = [f"### {self.poll['question']}\n"]
        for opt in self.poll["options"]:
            marker = "✓" if opt["id"] in correct_set else "✗"
            lines.append(f"- [{marker}] {opt['text']}")
        lines.append("")
        self.quiz_md_content += "\n".join(lines) + "\n"


poll_state = PollState()
