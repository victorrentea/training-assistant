"""How often each wiki note's topic came up in the trainer's past sessions.

The graph gives every dot a glow in proportion (graph-glow.ts): a staple of his
trainings glows strongly, a topic that is new today does not glow at all.

The past is every earlier AI session folder next to this one that holds a wiki/ vault.
Note titles differ across sessions for the same idea (and some vaults are in
Romanian), so Claude Haiku does the matching: it gets every past note (title + lead
sentence, deduped by title) and the current notes, and returns, per current note, the
past notes about the same topic. The code then counts the distinct sessions those
came from. Scores are cached per (note slug, title) in <session>/wiki-cache/ (outside
wiki/, which is published), so a rebuild only asks about notes it has not scored yet,
and a failed or impossible call (no key, no network) just leaves those notes unlit.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from daemon import log

GLOW_FILE = "note-glow.json"
CACHE_DIR = "wiki-cache"
CACHE_FILE = "topic-frequency.json"
MODEL = "claude-haiku-5-5"
# $ per million tokens: input, cache write (5 min), cache read, output.
PRICE = {"input": 0.10, "cache_write": 0.125, "cache_read": 0.01, "output": 0.50}
LEAD_CHARS = 160
# Notes per request: keeps a first scoring of a big vault well inside max_tokens.
BATCH = 80
# Entry pages, not topics.
_SKIPPED_STEMS = {"home", "index"}


@dataclass(frozen=True)
class Note:
    slug: str  # Quartz's full slug, as in note-badges.json
    title: str
    lead: str


def quartz_slug(relative_path: str) -> str:
    """Quartz's slugifyFilePath for a vault page (quartz/util/path.ts), without '.md'."""
    segments = []
    for segment in relative_path.split("/"):
        segment = re.sub(r"\s", "-", segment)
        segment = segment.replace("&", "-and-").replace("%", "-percent").replace("?", "").replace("#", "")
        segments.append(segment)
    return "/".join(segments).rstrip("/")


_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
_EMBED = re.compile(r"!\[\[[^\]]*\]\]|!\[[^\]]*\]\([^)]*\)")
_WIKILINK = re.compile(r"\[\[([^\]|]*)(?:\|([^\]]*))?\]\]")
_MDLINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def lead_sentence(text: str) -> str:
    """The note's first paragraph that is not a heading, as plain text, cut to LEAD_CHARS."""
    body = _FRONTMATTER.sub("", text.replace("\r\n", "\n"), count=1)
    for paragraph in re.split(r"\n\s*\n", body):
        paragraph = _EMBED.sub("", paragraph).strip()
        if not paragraph or paragraph.startswith("#"):
            continue
        paragraph = _WIKILINK.sub(lambda m: m.group(2) or m.group(1), paragraph)
        paragraph = _MDLINK.sub(r"\1", paragraph)
        paragraph = re.sub(r"^\s*(?:[-*+>]|\d+\.)\s+", "", paragraph, flags=re.M)
        paragraph = re.sub(r"[*_`]", "", paragraph)
        paragraph = " ".join(paragraph.split())
        if paragraph:
            return paragraph if len(paragraph) <= LEAD_CHARS else paragraph[: LEAD_CHARS - 1].rstrip() + "…"
    return ""


def read_notes(wiki_dir: Path) -> list[Note]:
    """The vault's topic notes: every non-empty page except Home/index and .obsidian/."""
    notes = []
    for path in sorted(wiki_dir.rglob("*.md")):
        relative = path.relative_to(wiki_dir)
        if ".obsidian" in relative.parts or path.stem.lower() in _SKIPPED_STEMS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not text.strip():
            continue
        notes.append(Note(quartz_slug(relative.with_suffix("").as_posix()), path.stem, lead_sentence(text)))
    return notes


_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")


def session_date(name: str) -> date | None:
    """'2026-09-21..23 Arch@DB' → 2026-09-21 (the first day)."""
    match = _DATE.match(name)
    if not match:
        return None
    try:
        return date(*map(int, match.groups()))
    except ValueError:
        return None


# Only AI sessions count: a Spring or testing workshop's wiki would just make every AI
# topic look rarer (Victor, 2026-10-10). Recognised by name: "AI@Kambi",
# "Agentic.how", "Gray Factory @ devoxx", "Agentic Reconversion keynote @ devoxx".
_AI_SESSION = re.compile(r"\bAI\b|(?i:agentic|factory)")


def is_ai_session(name: str) -> bool:
    return bool(_AI_SESSION.search(name))


def past_sessions(session_folder: Path) -> list[Path]:
    """Earlier AI sessions (by the date in the folder name) next to this one that have a wiki."""
    current = session_date(session_folder.name)
    if current is None:
        return []
    try:
        siblings = list(session_folder.parent.iterdir())
    except OSError:
        return []
    past = []
    for folder in siblings:
        day = session_date(folder.name)
        if (
            day is not None
            and day < current
            and folder != session_folder
            and is_ai_session(folder.name)
            and (folder / "wiki").is_dir()
        ):
            past.append((day, folder.name, folder))
    return [folder for _, _, folder in sorted(past)]


@dataclass
class PastTopic:
    title: str
    lead: str
    sessions: set[int]


def past_topics(sessions: list[Path]) -> list[PastTopic]:
    """Every past note once: notes titled alike (any case) in several sessions are one topic."""
    by_title: dict[str, PastTopic] = {}
    for index, folder in enumerate(sessions):
        for note in read_notes(folder / "wiki"):
            topic = by_title.setdefault(note.title.casefold(), PastTopic(note.title, note.lead, set()))
            topic.sessions.add(index)
            if note.lead:
                topic.lead = note.lead  # sessions come oldest first: keep the latest wording
    return list(by_title.values())


def _line(prefix: str, number: int, title: str, lead: str) -> str:
    return f"{prefix}{number}. {title} — {lead}" if lead else f"{prefix}{number}. {title}"


INSTRUCTIONS = """You match workshop notes by topic.

A trainer runs workshops on AI-assisted coding (and a few on testing, architecture and
Spring). After each workshop his notes become a wiki of short notes, one idea each:
a title and its lead sentence. Some notes are in Romanian.

Below are the notes of his PAST workshops (P-numbers). The user then sends notes of
TODAY's workshop (C-numbers). For every current note, list the past notes that are
about the same topic: a participant who read the past note would say "we covered this
one before". Same concept, tool, technique or idea counts even when titled differently,
worded differently or written in another language. A past note that only belongs to the
same broad area, or merely mentions the topic in passing, does not count. A current note
on something never covered before gets an empty list.

Answer with every current note exactly once."""

SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "note": {"type": "integer", "description": "the current note's C-number"},
                    "past": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "P-numbers of past notes about the same topic",
                    },
                },
                "required": ["note", "past"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["matches"],
    "additionalProperties": False,
}


def call_claude(api_key: str, past_block: str, current_block: str) -> tuple[dict, dict]:
    """One Haiku request → (parsed answer, token usage). Patched out in tests."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=180.0)
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=[
            {"type": "text", "text": INSTRUCTIONS},
            # The big block every request of a session shares: cached between batches.
            {"type": "text", "text": past_block, "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user", "content": current_block}],
    )
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"stop_reason={response.stop_reason}")
    text = next(block.text for block in response.content if block.type == "text")
    usage = response.usage
    return json.loads(text), {
        "input": usage.input_tokens,
        "cache_write": usage.cache_creation_input_tokens or 0,
        "cache_read": usage.cache_read_input_tokens or 0,
        "output": usage.output_tokens,
    }


def cost_usd(usage: dict) -> float:
    return sum(usage.get(kind, 0) * price for kind, price in PRICE.items()) / 1_000_000


def _load_cache(path: Path, past_names: list[str]) -> dict[str, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    # Another set of past sessions (one renamed, a wiki added late): every count is stale.
    if not isinstance(data, dict) or data.get("past") != past_names:
        return {}
    notes = data.get("notes")
    return notes if isinstance(notes, dict) else {}


def _save_cache(path: Path, past_names: list[str], notes: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"model": MODEL, "past": past_names, "notes": dict(sorted(notes.items()))}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _api_key() -> str | None:
    if os.environ.get("LLM_ADAPTER") == "stub":
        return None  # hermetic tests: never a real call
    from daemon.config import load_secrets_env

    load_secrets_env()
    return os.environ.get("ANTHROPIC_API_KEY") or None


def score(session_folder: Path) -> tuple[dict[str, int], int]:
    """({slug: number of past sessions that covered its topic}, number of past sessions).

    Notes it could not score (no key, API failure) are left out: they get no glow.
    """
    sessions = past_sessions(session_folder)
    notes = read_notes(session_folder / "wiki")
    if not sessions or not notes:
        return {}, len(sessions)
    past_names = [folder.name for folder in sessions]
    cache_path = session_folder / CACHE_DIR / CACHE_FILE
    cached = _load_cache(cache_path, past_names)
    todo = [n for n in notes if (cached.get(n.slug) or {}).get("title") != n.title]
    if todo:
        scored = _score_new(todo, sessions, cached)
        if scored != cached:
            _save_cache(cache_path, past_names, scored)
        cached = scored
    current = {n.slug for n in notes}
    seen = {slug: int(entry["seen"]) for slug, entry in cached.items() if slug in current}
    return seen, len(sessions)


def _score_new(todo: list[Note], sessions: list[Path], cached: dict[str, dict]) -> dict[str, dict]:
    api_key = _api_key()
    if not api_key:
        log.info("wiki", f"topic glow: no Claude API key — {len(todo)} notes left unscored")
        return cached
    topics = past_topics(sessions)
    past_block = "<past_notes>\n" + "\n".join(
        _line("P", i, t.title, t.lead) for i, t in enumerate(topics, 1)
    ) + "\n</past_notes>"
    cached = dict(cached)
    total = {kind: 0 for kind in PRICE}
    for start in range(0, len(todo), BATCH):
        batch = todo[start : start + BATCH]
        current_block = "<current_notes>\n" + "\n".join(
            _line("C", i, n.title, n.lead) for i, n in enumerate(batch, 1)
        ) + "\n</current_notes>"
        try:
            answer, usage = call_claude(api_key, past_block, current_block)
        except Exception as exc:  # noqa: BLE001 — the wiki must publish without the glow
            log.error("wiki", f"topic glow: Claude call failed, {len(batch)} notes unscored: {exc}")
            continue
        for kind in total:
            total[kind] += usage.get(kind, 0)
        for match in answer.get("matches", []):
            number = match.get("note")
            if not isinstance(number, int) or not 1 <= number <= len(batch):
                continue
            seen_in: set[int] = set()
            for p in match.get("past", []):
                if isinstance(p, int) and 1 <= p <= len(topics):
                    seen_in |= topics[p - 1].sessions
            note = batch[number - 1]
            cached[note.slug] = {"title": note.title, "seen": len(seen_in)}
    if any(total.values()):
        cost = cost_usd(total)
        _track(total, cost)
        log.info(
            "wiki",
            f"💸 topic glow: {len(todo)} notes vs {len(topics)} past notes in {len(sessions)} sessions — "
            f"in={total['input']} cache_w={total['cache_write']} cache_r={total['cache_read']} "
            f"out={total['output']} ${cost:.4f}",
        )
    return cached


def _track(usage: dict, cost: float) -> None:
    """Add to the daemon's running LLM spend (daemon/llm/adapter.py)."""
    try:
        from daemon.llm.adapter import get_usage
    except Exception:  # noqa: BLE001
        return
    running = get_usage()
    running.input_tokens += usage["input"] + usage["cache_write"] + usage["cache_read"]
    running.output_tokens += usage["output"]
    running.estimated_cost_usd += cost


def write_note_glow(wiki_dir: Path, out_dir: Path) -> None:
    """Write {"sessions": N, "seen": {slug: n}} at the site root for the graph's glow.

    The session folder is the vault's parent. Never raises: without scores, no glow.
    """
    try:
        seen, sessions = score(wiki_dir.parent)
    except Exception as exc:  # noqa: BLE001
        log.error("wiki", f"topic glow skipped: {exc}")
        seen, sessions = {}, 0
    payload = {"sessions": sessions, "seen": seen}
    (out_dir / GLOW_FILE).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
