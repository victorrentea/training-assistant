"""AI-share feature state — a short anonymous survey about AI in your code.

A fixed list of questions (QUESTIONS): sliders 0..100 (e.g. "how much of your
code does AI generate?") and Yes / No / I don't know choices (stored as the
option index). Participants answer them one after another; the host sees every
answer live; participants see everyone's answers only after the host flips
`revealed` on. Everything leaving the daemon is anonymous — no names, no UUIDs.
Module-level singleton, persisted via the 3-second session-state snapshot loop
(see daemon/__main__.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field

MIN_VALUE = 0
MAX_VALUE = 100

YES_NO_IDK = ["Yes", "No", "I don't know"]
YES_NO = ["Yes", "No"]

QUESTIONS: list[dict] = [
    {"id": "harness", "kind": "choice", "text": "What harness are you using?",
     "options": ["Claude Code / Codex", "Copilot CLI", "Copilot Chat in VS Code", "Copilot Chat in IntelliJ", "Other"]},
    {"id": "agents_md", "kind": "choice", "text": "Do you have an AGENTS.md / CLAUDE.md in your project?",
     "options": YES_NO_IDK, "host_options": ["Yes", "No / don't know"], "host_option_of": [0, 1, 1]},
    {"id": "mcp", "kind": "choice", "text": "Ever used an MCP tool?", "options": YES_NO_IDK},
    {"id": "skill", "kind": "choice", "text": "Ever created a skill?", "options": YES_NO},
    {"id": "plugins", "kind": "choice", "text": "Company plugins installed in your agent?", "options": YES_NO_IDK},
    {"id": "custom_agent", "kind": "choice", "text": "Ever created a custom agent (.md)?", "options": YES_NO},
    {"id": "code_review", "kind": "choice", "text": "Do you have a code-review skill / agent?", "options": YES_NO_IDK},
    {"id": "ai_generated", "kind": "slider", "text": "How much% of your🫵 code is AI-generated?",
     "low": "0% – ✍️ All by hand", "high": "100% – All by AI 🤖", "future": 95},
    {"id": "review", "kind": "slider", "text": "How much% of the AI-generated code do you review?",
     "low": "0% – 🙈 None", "high": "100% – Every line 🔍"},
]
QUESTIONS_BY_ID = {q["id"]: q for q in QUESTIONS}


def valid_value(qid: str, value: int) -> bool:
    q = QUESTIONS_BY_ID.get(qid)
    if q is None:
        return False
    if q["kind"] == "choice":
        return 0 <= value < len(q["options"])
    return MIN_VALUE <= value <= MAX_VALUE


@dataclass
class AiShareState:
    active: bool = False
    revealed: bool = False
    answers: dict[str, dict[str, int]] = field(default_factory=dict)
    # answers[question_id][participant_uuid] = slider 0..100 | choice option index

    def start(self) -> None:
        """Open a fresh round: questions enabled, previous answers dropped."""
        self.active = True
        self.revealed = False
        self.answers.clear()

    def set_value(self, pid: str, qid: str, value: int) -> bool:
        """Record a participant's answer. Returns False when not accepted."""
        if not self.active or not valid_value(qid, value):
            return False
        self.answers.setdefault(qid, {})[pid] = value
        return True

    def reset(self) -> None:
        self.active = False
        self.revealed = False
        self.answers.clear()

    def answers_of(self, pid: str) -> dict[str, int]:
        return {qid: per[pid] for qid, per in self.answers.items() if pid in per}

    def results(self) -> list[dict]:
        """Anonymous per-question results, in QUESTIONS order:
        sliders get every value (sorted), choices a count per option."""
        out = []
        for q in QUESTIONS:
            values = sorted((self.answers.get(q["id"]) or {}).values())
            item: dict = {"id": q["id"], "count": len(values)}
            if q["kind"] == "choice":
                item["counts"] = [values.count(i) for i in range(len(q["options"]))]
            else:
                item["values"] = values
            out.append(item)
        return out

    def snapshot(self) -> dict:
        return {"active": self.active, "revealed": self.revealed,
                "answers": {qid: dict(per) for qid, per in self.answers.items()}}

    def restore(self, data: dict | None) -> None:
        if not isinstance(data, dict):
            return
        self.active = bool(data.get("active", False))
        self.revealed = bool(data.get("revealed", False))
        raw = data.get("answers")
        if not raw and isinstance(data.get("values"), dict):
            # Legacy single-question shape: values[uuid] = 0..100 for "ai_generated".
            raw = {"ai_generated": data["values"]}
        if not isinstance(raw, dict):
            raw = {}
        self.answers = {}
        for qid, per in raw.items():
            if not isinstance(per, dict):
                continue
            kept = {str(pid): int(v) for pid, v in per.items()
                    if isinstance(v, (int, float)) and valid_value(str(qid), int(v))}
            if kept:
                self.answers[str(qid)] = kept


aishare_state = AiShareState()
