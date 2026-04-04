"""Code review state cache for daemon.

Owns the code review state (snippet, language, phase, selections, confirmed).
Initial data comes from daemon_state_push on WS connect.
"""
import threading


class CodeReviewState:
    """Code review state. Mutation methods run on uvicorn's single-threaded
    event loop (no lock needed). sync_from_restore runs on the main thread
    and uses _lock for cross-thread safety.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.snippet: str | None = None
        self.language: str | None = None
        self.phase: str = "idle"  # "idle" | "selecting" | "reviewing"
        self.selections: dict[str, set[int]] = {}  # pid → set of selected line numbers
        self.confirmed: set[int] = set()  # lines confirmed by host

    def sync_from_restore(self, data: dict):
        """Update from daemon_state_push. Called from main thread."""
        with self._lock:
            if "codereview_snippet" in data:
                self.snippet = data["codereview_snippet"]
            if "codereview_language" in data:
                self.language = data["codereview_language"]
            if "codereview_phase" in data:
                self.phase = data["codereview_phase"]
            if "codereview_selections" in data:
                self.selections.clear()
                for pid, lines in data["codereview_selections"].items():
                    self.selections[pid] = set(lines)
            if "codereview_confirmed" in data:
                self.confirmed.clear()
                self.confirmed.update(data["codereview_confirmed"])

    def create(self, snippet: str, language: str | None):
        """Set snippet+language, phase=selecting, clear selections+confirmed."""
        self.snippet = snippet
        self.language = language
        self.phase = "selecting"
        self.selections.clear()
        self.confirmed.clear()

    def close_selection(self):
        """Transition phase from selecting to reviewing."""
        self.phase = "reviewing"

    def select_lines(self, pid: str, lines: list[int]):
        """Full replacement of pid's selection (only valid lines)."""
        if self.snippet is None:
            return
        line_count = len(self.snippet.splitlines())
        valid_lines = {ln for ln in lines if 0 <= ln < line_count}
        self.selections[pid] = valid_lines

    def confirm_line(self, line: int) -> list[str]:
        """Mark line as confirmed; return list of pids who had that line selected."""
        self.confirmed.add(line)
        awarded_pids = [pid for pid, selected in self.selections.items() if line in selected]
        return awarded_pids

    def clear(self):
        """Reset all state to idle."""
        self.snippet = None
        self.language = None
        self.phase = "idle"
        self.selections.clear()
        self.confirmed.clear()

    def snapshot(self) -> dict:
        """Return a dict copy of current state."""
        return {
            "snippet": self.snippet,
            "language": self.language,
            "phase": self.phase,
            "selections": {pid: list(lines) for pid, lines in self.selections.items()},
            "confirmed": sorted(self.confirmed),
        }


# Module-level singleton
codereview_state = CodeReviewState()
