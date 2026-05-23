"""Poll feature state — host draft + started flag.

Mirrors the daemon/quiz/state.py pattern: module-level singleton, mutable in place.
No persistence — state lives only in memory and resets on daemon restart.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel


class PollData(BaseModel):
    """Latest draft pushed by the host composer."""
    question: str
    options: list[str]
    multi: bool
    public: bool


@dataclass
class PollState:
    data: Optional[PollData] = None
    started: bool = False

    def reset(self) -> None:
        self.data = None
        self.started = False


poll_state = PollState()
