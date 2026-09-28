"""AI-share feature state — "how much of your code does AI generate?" slider.

Each participant drags a 0..100 slider (0 = all by hand, 100 = all by AI).
The host sees every answer live; participants see everyone's answers only
after the host flips `revealed` on. Module-level singleton, persisted via the
3-second session-state snapshot loop (see daemon/__main__.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field

MIN_VALUE = 0
MAX_VALUE = 100


@dataclass
class AiShareState:
    active: bool = False
    revealed: bool = False
    values: dict[str, int] = field(default_factory=dict)
    # values[participant_uuid] = 0..100

    def start(self) -> None:
        """Open a fresh round: sliders enabled, previous answers dropped."""
        self.active = True
        self.revealed = False
        self.values.clear()

    def set_value(self, pid: str, value: int) -> bool:
        """Record a participant's answer. Returns False when not accepted."""
        if not self.active or not MIN_VALUE <= value <= MAX_VALUE:
            return False
        self.values[pid] = value
        return True

    def reset(self) -> None:
        self.active = False
        self.revealed = False
        self.values.clear()

    def points(self, names: dict[str, str]) -> list[dict]:
        """UUID-free answers: [{name, value}], sorted by value then name."""
        pts = [
            {"name": names.get(pid) or "?", "value": value}
            for pid, value in self.values.items()
        ]
        pts.sort(key=lambda p: (p["value"], p["name"].lower()))
        return pts

    def snapshot(self) -> dict:
        return {"active": self.active, "revealed": self.revealed, "values": dict(self.values)}

    def restore(self, data: dict | None) -> None:
        if not isinstance(data, dict):
            return
        self.active = bool(data.get("active", False))
        self.revealed = bool(data.get("revealed", False))
        self.values = {
            str(pid): int(v) for pid, v in (data.get("values") or {}).items()
            if isinstance(v, (int, float)) and MIN_VALUE <= v <= MAX_VALUE
        }


aishare_state = AiShareState()
