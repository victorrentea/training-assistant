"""AI-share feature state — a short anonymous survey about AI in your code.

A fixed list of questions (QUESTIONS): sliders 0..100 (e.g. "how much of your
code does AI generate?"), Yes / No / I don't know choices (stored as the
option index), multi choices (stored as a bitmask of the ticked options,
plus a bitmask of the ❤️ favourites among them) and a ranking (a list of items,
seeded from its options, that participants grow and 🔥 (upvote), re-ordered by
score live for everyone). Participants answer them one after another; the host sees every
answer live; participants see everyone's answers only after the host flips
`revealed` on. Everything leaving the daemon is anonymous — no names, no UUIDs.
Module-level singleton, persisted via the 3-second session-state snapshot loop
(see daemon/__main__.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field

MIN_VALUE = 0
MAX_VALUE = 100
MAX_OTHER_LEN = 60
MAX_ITEM_LEN = 60
MAX_ITEMS_PER_PARTICIPANT = 5
MAX_ITEMS = 60

YES_NO_IDK = ["Yes", "No", "I don't know"]
YES_NO = ["Yes", "No"]

QUESTIONS: list[dict] = [
    {"id": "harness_work", "kind": "multi", "text": "What agent harness do you use at work?",
     "hint": "…then click ❤️ on your favourite", "options": ["Claude Code / Codex", "Copilot CLI", "Copilot Chat in VS Code", "Copilot Chat in IntelliJ", "Other"],
     "other_option": 4},
    {"id": "personal_sub", "kind": "choice", "text": "Do you have a personal Claude / Codex subscription?",
     "links": [{"text": "Claude", "url": "https://claude.com/pricing"},
               {"text": "Codex", "url": "https://developers.openai.com/codex/pricing"}],
     "options": YES_NO},
    {"id": "agents_md", "kind": "choice", "text": "Do you have an AGENTS.md (or CLAUDE.md) in 🫵your project?",
     "links": [{"text": "AGENTS.md", "url": "https://agents.md"}],
     "options": ["Yes", "No / I don't know"]},
    {"id": "knowledge_base", "kind": "choice",
     "text": "Does your team's agent use a (Markdown) knowledge base of your project, built from its code (e.g. LLM Wiki)?",
     "links": [{"text": "LLM Wiki", "url": "https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f"}],
     "options": ["Yes", "No / I don't know"]},
    {"id": "mcp", "kind": "choice", "text": "Used an MCP tool?", "options": YES_NO_IDK},
    {"id": "skill", "kind": "choice", "text": "Created a skill?", "options": YES_NO},
    {"id": "plugins", "kind": "choice", "text": "Do you have any plugins installed in your agent? (company or team)", "options": YES_NO_IDK},
    {"id": "custom_agent", "kind": "choice", "text": "Created a custom agent (e.g. .claude/agents/*.md)?", "options": YES_NO},
    {"id": "code_review", "kind": "choice", "text": "Do you have a code-review skill / agent?", "options": YES_NO_IDK},
    {"id": "nontech_pr", "kind": "choice", "text": "Received a PR written by a non-developer (e.g. PO, business)?", "options": YES_NO},
    {"id": "ai_generated", "kind": "slider", "text": "How much% of the code you🫵 push is AI-generated?",
     "low": "0% – ✍️ All by hand", "high": "100% – All by AI 🤖", "future": 90,
     "future_link": {"text": "½ of devs by end of 2026 ↗",
                     "url": "https://www.youtube.com/watch?v=wc8FBhQtdsA&t=2405s"}},
    {"id": "review", "kind": "slider", "text": "How much of that code do you review?",
     "low": "0% – 🙈 None", "high": "100% – Every line 🔍"},
    {"id": "devex_pain", "kind": "ranking", "text": "DevEx: What burns your ⏱️ time, 🧠 brain or 😡 emotions?",
     "hint": "… add your own",
     # "Key: detail" — the key is shown in bold; items participants add follow the same rule.
     "options": ["Code Review: waiting / performing", "Meetings: too many / too long", "Bureaucracy",
                 "Tech debt: legacy code, lack of tests", "Requirements: unclear / ever-changing", "Context switching",
                 "Permissions: lack of access", "CI: slow pipeline / flaky tests", "Blocked: by other teams",
                 "Documentation: missing or obsolete"]},
]
QUESTIONS_BY_ID = {q["id"]: q for q in QUESTIONS}

# Options merged after answers were given: old option index → new one, applied on restore.
# agents_md: "No" and "I don't know" became one option (2026-10-26).
MERGED_OPTIONS = {"agents_md": [0, 1, 1]}

# Seeded ranking items reworded after votes were cast: old text → new, applied on restore
# so a running survey keeps its 🔥. Items participants added (by != None) are never renamed.
RENAMED_ITEMS = {"devex_pain": {
    "Code review: waiting": "Code Review: waiting / performing",
    "Code review: waiting or giving": "Code Review: waiting / performing",
    "Meetings: long / too many": "Meetings: too many / too long",
    "Other teams: waiting on them": "Blocked: by other teams",
    "Process, bureaucracy": "Bureaucracy",
    "Bureaucracy: processes": "Bureaucracy",
    "Requirements: unclear / volatile": "Requirements: unclear / ever-changing",
}}


def valid_value(qid: str, value: int) -> bool:
    q = QUESTIONS_BY_ID.get(qid)
    if q is None or q["kind"] == "ranking":  # a ranking is voted on item by item, never answered with a value
        return False
    if q["kind"] == "choice":
        return 0 <= value < len(q["options"])
    if q["kind"] == "multi":
        return 0 <= value < 1 << len(q["options"])  # 0 = nothing ticked
    return MIN_VALUE <= value <= MAX_VALUE


def picked(q: dict, value: int, option: int | None) -> bool:
    """Is `option` part of answer `value` — the chosen index, or a ticked bit of a multi?"""
    if option is None:
        return False
    return bool(value >> option & 1) if q["kind"] == "multi" else value == option


@dataclass
class AiShareState:
    active: bool = False
    revealed: bool = False
    answers: dict[str, dict[str, int]] = field(default_factory=dict)
    # answers[question_id][participant_uuid] = slider 0..100 | choice option index
    others: dict[str, dict[str, str]] = field(default_factory=dict)
    # others[question_id][participant_uuid] = what they typed after picking the "other" option
    hearts: dict[str, dict[str, int]] = field(default_factory=dict)
    # hearts[question_id][participant_uuid] = bitmask of a multi's ❤️ options, always among the ticked ones
    items: dict[str, list[dict]] = field(default_factory=dict)
    # items[question_id] = a ranking's items [{"id", "text", "by"}]: its options (by=None) + what participants added
    votes: dict[str, dict[str, dict[int, int]]] = field(default_factory=dict)
    # votes[question_id][participant_uuid][item_id] = 1 (🔥)

    def _seed_items(self) -> None:
        """A ranking starts from its options; the host may delete them like any added item."""
        for q in QUESTIONS:
            if q["kind"] == "ranking" and q["id"] not in self.items:
                self.items[q["id"]] = [{"id": i, "text": t, "by": None} for i, t in enumerate(q["options"])]

    def start(self) -> None:
        """Open a fresh round: questions enabled, previous answers dropped."""
        self.reset()
        self.active = True
        self._seed_items()

    def set_value(self, pid: str, qid: str, value: int, other: str | None = None,
                  hearts: int = 0) -> bool:
        """Record a participant's answer. Returns False when not accepted.
        `other` is kept only alongside the question's "other" option; on a multi,
        `hearts` is the bitmask of ❤️ options (only ticked ones are kept) and value 0 withdraws the answer."""
        if not self.active or not valid_value(qid, value):
            return False
        q = QUESTIONS_BY_ID[qid]
        if q["kind"] == "multi" and value == 0:
            for per in (self.answers, self.others, self.hearts):
                per.get(qid, {}).pop(pid, None)
            return True
        self.answers.setdefault(qid, {})[pid] = value
        has_other = picked(q, value, q.get("other_option"))
        text = (other or "").strip()[:MAX_OTHER_LEN]
        if text and has_other:
            self.others.setdefault(qid, {})[pid] = text
        elif other is not None or not has_other:
            self.others.get(qid, {}).pop(pid, None)
        if q["kind"] == "multi":
            if hearts & value:
                self.hearts.setdefault(qid, {})[pid] = hearts & value
            else:
                self.hearts.get(qid, {}).pop(pid, None)
        return True

    def reset(self) -> None:
        self.active = False
        self.revealed = False
        self.answers.clear()
        self.others.clear()
        self.hearts.clear()
        self.items.clear()
        self.votes.clear()

    def _ranking_items(self, qid: str) -> list[dict] | None:
        q = QUESTIONS_BY_ID.get(qid)
        if not self.active or q is None or q["kind"] != "ranking":
            return None
        return self.items.setdefault(qid, [])

    def vote(self, pid: str, qid: str, item_id: int, vote: int) -> bool:
        """🔥 (1) or take it back (0). False when there is no such item."""
        items = self._ranking_items(qid)
        if items is None or vote not in (0, 1) or not any(it["id"] == item_id for it in items):
            return False
        mine = self.votes.setdefault(qid, {}).setdefault(pid, {})
        if vote:
            mine[item_id] = vote
        else:
            mine.pop(item_id, None)
            if not mine:
                self.votes[qid].pop(pid, None)
        return True

    def add_item(self, pid: str, qid: str, text: str) -> int | None:
        """A participant adds an item and gives it their 🔥. The same text (case aside)
        just gets their 🔥. Returns the item id, or None when not accepted."""
        items = self._ranking_items(qid)
        text = " ".join((text or "").split())[:MAX_ITEM_LEN]
        if items is None or not text:
            return None
        same = next((it for it in items if it["text"].lower() == text.lower()), None)
        if same is None:
            if len(items) >= MAX_ITEMS or sum(it["by"] == pid for it in items) >= MAX_ITEMS_PER_PARTICIPANT:
                return None
            same = {"id": max((it["id"] for it in items), default=-1) + 1, "text": text, "by": pid}
            items.append(same)
        self.vote(pid, qid, same["id"], 1)
        return same["id"]

    def delete_item(self, qid: str, item_id: int) -> bool:
        """Host moderation: the item and every vote on it are gone."""
        items = self._ranking_items(qid)
        if items is None or not any(it["id"] == item_id for it in items):
            return False
        self.items[qid] = [it for it in items if it["id"] != item_id]
        for pid, mine in list(self.votes.get(qid, {}).items()):
            mine.pop(item_id, None)
            if not mine:
                del self.votes[qid][pid]
        return True

    def ranked(self, qid: str) -> list[dict]:
        """A ranking's items, best first: most 🔥, then the oldest."""
        score: dict[int, int] = {}
        for mine in (self.votes.get(qid) or {}).values():
            for item_id in mine:
                score[item_id] = score.get(item_id, 0) + 1
        out = [{"id": it["id"], "text": it["text"], "score": score.get(it["id"], 0)} for it in self.items.get(qid) or []]
        out.sort(key=lambda r: (-r["score"], r["id"]))
        return out

    def votes_of(self, pid: str) -> dict[str, dict[str, int]]:
        return {qid: {str(i): v for i, v in per[pid].items()} for qid, per in self.votes.items() if per.get(pid)}

    def answers_of(self, pid: str) -> dict[str, int]:
        return {qid: per[pid] for qid, per in self.answers.items() if pid in per}

    def others_of(self, pid: str) -> dict[str, str]:
        return {qid: per[pid] for qid, per in self.others.items() if pid in per}

    def hearts_of(self, pid: str) -> dict[str, int]:
        return {qid: per[pid] for qid, per in self.hearts.items() if pid in per}

    def results(self) -> list[dict]:
        """Anonymous per-question results, in QUESTIONS order:
        sliders get every value (sorted), choices a count per option,
        multis a count per ticked option and a ❤️ count per option."""
        out = []
        for q in QUESTIONS:
            values = sorted((self.answers.get(q["id"]) or {}).values())
            item: dict = {"id": q["id"], "count": len(values)}
            if q["kind"] == "ranking":
                item["count"] = len(self.votes.get(q["id"]) or {})
                item["items"] = self.ranked(q["id"])
            elif q["kind"] == "slider":
                item["values"] = values
            else:
                n = len(q["options"])
                if q["kind"] == "multi":
                    item["counts"] = [sum(v >> i & 1 for v in values) for i in range(n)]
                    hearts = (self.hearts.get(q["id"]) or {}).values()
                    item["hearts"] = [sum(h >> i & 1 for h in hearts) for i in range(n)]
                else:
                    item["counts"] = [values.count(i) for i in range(n)]
                if "other_option" in q:
                    item["others"] = sorted((self.others.get(q["id"]) or {}).values(), key=str.lower)
            out.append(item)
        return out

    def snapshot(self) -> dict:
        return {"active": self.active, "revealed": self.revealed,
                "answers": {qid: dict(per) for qid, per in self.answers.items()},
                "others": {qid: dict(per) for qid, per in self.others.items()},
                "hearts": {qid: dict(per) for qid, per in self.hearts.items()},
                "items": {qid: [dict(it) for it in its] for qid, its in self.items.items()},
                "votes": {qid: {pid: {str(i): v for i, v in mine.items()} for pid, mine in per.items()}
                          for qid, per in self.votes.items()}}

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
            merged = MERGED_OPTIONS.get(str(qid))
            kept = {str(pid): merged[int(v)] if merged and 0 <= int(v) < len(merged) else int(v)
                    for pid, v in per.items() if isinstance(v, (int, float))}
            kept = {pid: v for pid, v in kept.items() if valid_value(str(qid), v)}
            if kept:
                self.answers[str(qid)] = kept
        raw_others = data.get("others")
        self.others = {
            str(qid): {str(pid): str(t)[:MAX_OTHER_LEN] for pid, t in per.items() if isinstance(t, str) and t.strip()}
            for qid, per in (raw_others.items() if isinstance(raw_others, dict) else [])
            if isinstance(per, dict)
        }
        raw_hearts = data.get("hearts")
        if not isinstance(raw_hearts, dict) and isinstance(data.get("favorites"), dict):
            # Legacy shape: a single ❤️ per participant, stored as its option index.
            raw_hearts = {qid: {pid: 1 << i for pid, i in per.items() if isinstance(i, int) and 0 <= i < 32}
                          for qid, per in data["favorites"].items() if isinstance(per, dict)}
        self.hearts = {}
        for qid, per in (raw_hearts.items() if isinstance(raw_hearts, dict) else []):
            if not isinstance(per, dict):
                continue
            ticked = self.answers.get(str(qid), {})
            kept = {str(pid): h & ticked[str(pid)] for pid, h in per.items()
                    if isinstance(h, int) and h & ticked.get(str(pid), 0)}
            if kept:
                self.hearts[str(qid)] = kept
        raw_items = data.get("items")
        self.items = {}
        for qid, its in (raw_items.items() if isinstance(raw_items, dict) else []):
            if isinstance(its, list):
                renamed = RENAMED_ITEMS.get(str(qid), {})
                self.items[str(qid)] = [
                    {"id": int(it["id"]),
                     "text": (str(it["text"]) if it.get("by") else renamed.get(str(it["text"]), str(it["text"])))[:MAX_ITEM_LEN],
                     "by": str(it["by"]) if it.get("by") else None}
                    for it in its if isinstance(it, dict) and isinstance(it.get("id"), int) and it.get("text")]
        if self.active:
            self._seed_items()  # a snapshot from before rankings existed
        raw_votes = data.get("votes")
        self.votes = {}
        for qid, per in (raw_votes.items() if isinstance(raw_votes, dict) else []):
            ids = {it["id"] for it in self.items.get(str(qid), [])}
            for pid, mine in (per.items() if isinstance(per, dict) else []):
                kept = {int(i): v for i, v in (mine.items() if isinstance(mine, dict) else [])
                        if str(i).isdigit() and int(i) in ids and v == 1}  # a ▼ from before upvote-only is dropped
                if kept:
                    self.votes.setdefault(str(qid), {})[str(pid)] = kept


aishare_state = AiShareState()
