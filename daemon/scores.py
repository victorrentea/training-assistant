"""Global score authority — daemon owns all scoring."""
import hashlib
import hmac
import secrets
import threading

# Per-daemon-run secret used to derive participant-facing score tokens.
# SECURITY: the participant-facing ``scores_updated`` broadcast is delivered
# identically to every participant, so it cannot embed each viewer's private
# score directly. Instead each participant is keyed by an opaque, non-identifying
# token derived HMAC-style from its UUID with this per-run secret. The token:
#   • is NOT the participant's X-Participant-ID, so it can never be replayed as an
#     identity to impersonate anyone or evade per-UUID rate limits;
#   • is not reversible to the UUID (HMAC-SHA256 truncated) — leaking it to other
#     participants discloses nothing about who owns which score;
#   • is stable for the lifetime of one daemon run (so live badge updates match)
#     and rotates on restart (participants re-fetch their token from GET /state on
#     reconnect, staying in sync).
# The owning participant learns ONLY its own token via GET /state (my_score_token).
_SCORE_TOKEN_SECRET = secrets.token_bytes(32)


def score_token(pid: str) -> str:
    """Derive the opaque, non-identifying participant-facing score token for a UUID.

    16 hex chars (64 bits) — enough to avoid collisions in a session while being
    visibly NOT a UUID (no dashes, wrong length), so the no-UUID wire guard passes.
    """
    return hmac.new(_SCORE_TOKEN_SECRET, pid.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


class Scores:
    def __init__(self):
        self._lock = threading.Lock()
        self.scores: dict[str, int] = {}
        self.base_scores: dict[str, int] = {}

    def add_score(self, pid: str, points: int):
        with self._lock:
            self.scores[pid] = self.scores.get(pid, 0) + points

    def snapshot_base(self):
        """Capture current scores as base (called when quiz opens)."""
        with self._lock:
            self.base_scores = dict(self.scores)

    def reset(self):
        with self._lock:
            self.scores.clear()
            self.base_scores.clear()

    def sync_from_restore(self, data: dict):
        with self._lock:
            if "scores" in data:
                self.scores.clear()
                self.scores.update(data["scores"])
            if "base_scores" in data:
                self.base_scores.clear()
                self.base_scores.update(data.get("base_scores", {}))

    def snapshot(self) -> dict:
        return dict(self.scores)

    def snapshot_tokenized(self) -> dict[str, int]:
        """Participant-facing score map keyed by opaque token instead of UUID.

        SECURITY: this is the ONLY score map that may go out over the participant
        broadcast channel — it carries no UUIDs. Internal ``__``-prefixed ids
        (host/ai) are never scored but are skipped defensively.
        """
        with self._lock:
            return {
                score_token(pid): sc
                for pid, sc in self.scores.items()
                if not pid.startswith("__")
            }


scores = Scores()
