"""Poll state singleton — daemon owns all poll lifecycle."""
from datetime import datetime, timezone

_MAX_POINTS = 1000
_MIN_POINTS = 500
_SLOWEST_MULTIPLIER = 3


class PollState:
    def __init__(self):
        self.poll: dict | None = None
        self.poll_active: bool = False
        self.votes: dict[str, dict] = {}  # uuid → {"option_indices": list[int], "voted_at": str ISO}
        self.poll_opened_at: datetime | None = None
        self.poll_correct_indices: list[int] | None = None
        self.poll_timer_seconds: int | None = None
        self.poll_timer_started_at: datetime | None = None
        self._vote_counts_dirty: bool = True
        self._vote_counts_cache: list[int] | None = None
        self.awarded_points: dict[str, int] = {}  # pid → points awarded by most recent reveal_correct

    def create_poll(self, question: str, options: list[str], multi: bool = False,
                    correct_count: int | None = None) -> dict:
        import uuid as _uuid
        self.poll = {
            "id": _uuid.uuid4().hex[:8],
            "question": question,
            "options": options,
            "multi": multi,
        }
        if correct_count is not None:
            self.poll["correct_count"] = correct_count
        self.poll_active = False
        self.votes.clear()
        self.poll_correct_indices = None
        self.poll_timer_seconds = None
        self.poll_timer_started_at = None
        self._vote_counts_dirty = True
        self.awarded_points = {}
        return dict(self.poll)

    def open_poll(self, scores_snapshot_fn) -> None:
        self.poll_active = True
        self.poll_opened_at = datetime.now(timezone.utc)
        self.votes.clear()
        self._vote_counts_dirty = True
        scores_snapshot_fn()

    def close_poll(self) -> dict:
        self.poll_active = False
        # Once the poll is closed, any pending end-timer is meaningless. Leaving
        # these fields set lets a host that re-fetches /poll re-apply a stale
        # timer to the *next* poll on this client.
        self.poll_timer_seconds = None
        self.poll_timer_started_at = None
        counts = self.vote_counts()
        return {"vote_counts": counts}

    def cast_vote(self, pid: str, option_indices: list[int] | None = None) -> bool:
        if not self.poll or not self.poll_active:
            return False
        if pid in self.votes:
            return False
        if option_indices is None or not isinstance(option_indices, list):
            return False
        if not option_indices:
            return False
        n = len(self.poll["options"])
        is_multi = self.poll.get("multi", False)
        if is_multi:
            correct_count = self.poll.get("correct_count")
            max_allowed = correct_count if correct_count else n
            if (len(option_indices) > max_allowed
                    or len(set(option_indices)) != len(option_indices)
                    or not all(0 <= i < n for i in option_indices)):
                return False
        else:
            if len(option_indices) != 1 or not (0 <= option_indices[0] < n):
                return False
        voted_at = datetime.now(timezone.utc).isoformat()
        self.votes[pid] = {"option_indices": option_indices, "voted_at": voted_at}
        self._vote_counts_dirty = True
        return True

    def reveal_correct(self, correct_indices: list[int], scores_obj) -> dict:
        correct_set = set(correct_indices)
        n = len(self.poll["options"]) if self.poll else 0
        all_indices = set(range(n))
        wrong_set = all_indices - correct_set
        multi = self.poll.get("multi", False) if self.poll else False
        now = datetime.now(timezone.utc)
        opened_at = self.poll_opened_at or now

        # Reverse the awards from the previous reveal_correct (if any). This makes
        # reveal_correct idempotent: when the host changes which option is correct,
        # points flow off prior winners before flowing onto new winners.
        for pid, prev_pts in self.awarded_points.items():
            scores_obj.add_score(pid, -prev_pts)
        self.awarded_points = {}

        correct_voters = set()
        for pid, vote in self.votes.items():
            voted = set(vote["option_indices"])
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
            voted = set(vote["option_indices"])
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
                self.awarded_points[pid] = pts

        self.poll_correct_indices = list(correct_set)
        self._append_to_poll_md(correct_set)
        return {
            "correct_indices": list(correct_set),
            "scores": scores_obj.snapshot(),
            "votes": {pid: v["option_indices"] for pid, v in self.votes.items()},
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
        self.poll_correct_indices = None
        self.poll_timer_seconds = None
        self.poll_timer_started_at = None
        self._vote_counts_dirty = True
        self._vote_counts_cache = None
        self.awarded_points = {}

    def vote_counts(self) -> list[int]:
        if not self._vote_counts_dirty and self._vote_counts_cache is not None:
            return self._vote_counts_cache
        n = len(self.poll["options"]) if self.poll else 0
        counts = [0] * n
        for vote in self.votes.values():
            for idx in vote["option_indices"]:
                if 0 <= idx < n:
                    counts[idx] += 1
        self._vote_counts_cache = counts
        self._vote_counts_dirty = False
        return counts

    def _append_to_poll_md(self, correct_set: set[int]):
        if not self.poll:
            return
        lines = [f"### {self.poll['question']}\n"]
        for i, text in enumerate(self.poll["options"]):
            marker = "✓" if i in correct_set else "✗"
            lines.append(f"- [{marker}] {text}")
        lines.append("")
        entry = "\n".join(lines) + "\n"
        try:
            from daemon.misc.content_files import get_active_session_folder
            folder = get_active_session_folder()
            if folder is not None:
                (folder / "ai-quiz.md").open("a", encoding="utf-8").write(entry)
        except Exception:
            pass


poll_state = PollState()
