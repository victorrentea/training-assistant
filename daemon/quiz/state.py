"""Quiz state singleton — daemon owns all quiz lifecycle."""
from datetime import datetime, timezone

_MAX_POINTS = 1000
_MIN_POINTS = 500
_SLOWEST_MULTIPLIER = 3


class QuizState:
    def __init__(self):
        self.quiz: dict | None = None
        self.quiz_active: bool = False
        self.votes: dict[str, dict] = {}  # uuid → {"option_indices": list[int], "voted_at": str ISO}
        self.quiz_opened_at: datetime | None = None
        self.quiz_correct_indices: list[int] | None = None
        self.quiz_timer_seconds: int | None = None
        self.quiz_timer_started_at: datetime | None = None
        self._vote_counts_dirty: bool = True
        self._vote_counts_cache: list[int] | None = None
        self.awarded_points: dict[str, int] = {}  # pid → points awarded by most recent reveal_correct

    def create_quiz(self, question: str, options: list[str], multi: bool = False,
                    correct_count: int | None = None) -> dict:
        import uuid as _uuid
        self.quiz = {
            "id": _uuid.uuid4().hex[:8],
            "question": question,
            "options": options,
            "multi": multi,
        }
        if correct_count is not None:
            self.quiz["correct_count"] = correct_count
        self.quiz_active = False
        self.votes.clear()
        self.quiz_correct_indices = None
        self.quiz_timer_seconds = None
        self.quiz_timer_started_at = None
        self._vote_counts_dirty = True
        self.awarded_points = {}
        return dict(self.quiz)

    def open_quiz(self, scores_snapshot_fn) -> None:
        self.quiz_active = True
        self.quiz_opened_at = datetime.now(timezone.utc)
        self.votes.clear()
        self._vote_counts_dirty = True
        scores_snapshot_fn()

    def close_quiz(self) -> dict:
        self.quiz_active = False
        # Once the quiz is closed, any pending end-timer is meaningless. Leaving
        # these fields set lets a host that re-fetches /quiz re-apply a stale
        # timer to the *next* quiz on this client.
        self.quiz_timer_seconds = None
        self.quiz_timer_started_at = None
        counts = self.vote_counts()
        return {"vote_counts": counts}

    def cast_vote(self, pid: str, option_indices: list[int] | None = None) -> bool:
        if not self.quiz or not self.quiz_active:
            return False
        if option_indices is None or not isinstance(option_indices, list):
            return False
        if not option_indices:
            return False
        n = len(self.quiz["options"])
        is_multi = self.quiz.get("multi", False)
        if is_multi:
            correct_count = self.quiz.get("correct_count")
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
        n = len(self.quiz["options"]) if self.quiz else 0
        all_indices = set(range(n))
        wrong_set = all_indices - correct_set
        multi = self.quiz.get("multi", False) if self.quiz else False
        now = datetime.now(timezone.utc)
        opened_at = self.quiz_opened_at or now

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

        self.quiz_correct_indices = list(correct_set)
        self._append_to_quiz_md(correct_set)
        return {
            "correct_indices": list(correct_set),
            "scores": scores_obj.snapshot(),
            "votes": {pid: v["option_indices"] for pid, v in self.votes.items()},
        }

    def start_timer(self, seconds: int) -> dict:
        self.quiz_timer_seconds = seconds
        self.quiz_timer_started_at = datetime.now(timezone.utc)
        return {
            "seconds": seconds,
            "started_at": self.quiz_timer_started_at.isoformat(),
        }

    def clear(self) -> None:
        self.quiz = None
        self.quiz_active = False
        self.votes.clear()
        self.quiz_opened_at = None
        self.quiz_correct_indices = None
        self.quiz_timer_seconds = None
        self.quiz_timer_started_at = None
        self._vote_counts_dirty = True
        self._vote_counts_cache = None
        self.awarded_points = {}

    def vote_counts(self) -> list[int]:
        if not self._vote_counts_dirty and self._vote_counts_cache is not None:
            return self._vote_counts_cache
        n = len(self.quiz["options"]) if self.quiz else 0
        counts = [0] * n
        for vote in self.votes.values():
            for idx in vote["option_indices"]:
                if 0 <= idx < n:
                    counts[idx] += 1
        self._vote_counts_cache = counts
        self._vote_counts_dirty = False
        return counts

    def _append_to_quiz_md(self, correct_set: set[int]):
        if not self.quiz:
            return
        lines = [f"### {self.quiz['question']}\n"]
        for i, text in enumerate(self.quiz["options"]):
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


quiz_state = QuizState()
