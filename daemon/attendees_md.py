"""Live `attendees.md` attendance sheet for the active session.

The file is a *generated artifact*: on every roster/name change the whole file
is fully regenerated from the canonical participant enumerator
(`_build_host_participants_list()`). There is deliberately **no** managed-region
or hand-edit-preservation logic.

Header is derived from the session folder name + the date(s) parsed by
`_SESSION_FOLDER_RE` (there is no structured session metadata) plus an optional
Google Drive URL.

Anonymous / auto-assigned fictional names (LOTR + conference character pools)
are rendered distinctly from confirmed real names.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

ATTENDEES_FILENAME = "attendees.md"

# Prefixes of auto-generated fallback names assigned when the fictional pools
# are exhausted (Guest-<hex> in workshop mode, Hero-<id> in talk mode).
_FALLBACK_NAME_PREFIXES = ("Guest-", "Hero-")

# Markdown metacharacters neutralized when rendering an untrusted display name
# (or the folder-derived H1 title) into the sheet — defense-in-depth at the sink
# even though ingest sanitization already strips newlines/control chars.
# `-` and `.` are deliberately NOT escaped: mid-line they cannot begin a
# heading / thematic rule / list item (names are always preceded by a list
# marker), and escaping them would mangle hyphenated names ("Anne-Marie") and
# folder dates ("2026-07-24").
_MD_ESCAPE_CHARS = frozenset("\\`*_[]()<>|~!{}")


def _md_escape(text: str) -> str:
    """Neutralize Markdown so a name/title can't inject rows, headings, rules,
    links, images, emphasis, tables or raw HTML.

    Newlines/carriage returns are folded to spaces first (belt-and-suspenders:
    ingest already strips them) so a value can never break onto its own line and
    become structural markdown.
    """
    text = str(text).replace("\r", " ").replace("\n", " ")
    return "".join("\\" + ch if ch in _MD_ESCAPE_CHARS else ch for ch in text)


@lru_cache(maxsize=1)
def _fictional_names() -> frozenset[str]:
    """Names the daemon can auto-assign — used to flag anonymous attendees.

    A name from either fictional pool is treated as an anonymous / auto-assigned
    entry rather than a confirmed real name. This is a heuristic (a real person
    literally named "Frodo" would be flagged), acceptable for phase 1.
    """
    from daemon.participant.names import CHARACTER_NAMES, LOTR_NAMES

    return frozenset(LOTR_NAMES) | frozenset(n for n, _u in CHARACTER_NAMES)


def _is_anonymous_name(name: str) -> bool:
    """Name-only anonymity heuristic — the FALLBACK used only when a participant
    entry carries no uuid to look up the explicit signal (e.g. a legacy snapshot
    or a direct render call).

    True for fictional-pool members and pool-exhaustion fallbacks
    (Guest-XXXX / Hero-XXXX). Superseded, when identity is known, by the
    explicit ``anonymous_pids`` signal so a participant who deliberately types a
    real name matching a pool entry ("Frodo") is not mis-tagged.
    """
    return name in _fictional_names() or name.startswith(_FALLBACK_NAME_PREFIXES)


def _entry_is_anonymous(entry: dict, anonymous_pids: set[str] | None) -> bool:
    """Resolve anonymity for one roster entry.

    Prefers the explicit signal: when the entry carries a ``uuid`` and an
    ``anonymous_pids`` set is supplied, membership in that set is authoritative
    (a typed real name is never anonymous, even if it matches a fictional pool
    entry). Falls back to the name-only heuristic when no identity is available.
    """
    if anonymous_pids is not None and entry.get("uuid") is not None:
        return str(entry.get("uuid")) in anonymous_pids
    return _is_anonymous_name(str(entry.get("name", "")))


def _parse_header(folder: Path | None) -> tuple[str, str | None]:
    """Return (title, date_line) derived from the session folder name.

    date_line is None when no date could be parsed.
    """
    if folder is None:
        return "Session", None
    name = folder.name
    from daemon.config import _SESSION_FOLDER_RE

    m = _SESSION_FOLDER_RE.match(name)
    date_line: str | None = None
    if m:
        start = m.group(1)
        end = m.group(2)
        if end:
            # end may be a bare day ("25") or month-day ("06-25"); render as a range.
            date_line = f"{start} .. {end}"
        else:
            date_line = start
    return name, date_line


def render_attendees_md(
    folder: Path | None,
    participants: list[dict],
    gdrive_url: str | None = None,
    anonymous_pids: set[str] | None = None,
) -> str:
    """Render the whole `attendees.md` from the live roster (full regeneration).

    ``anonymous_pids`` is the explicit anonymity signal (participant uuids that
    joined via the auto-assign path). When supplied, an entry's anonymity is
    resolved from it by uuid; entries without a uuid fall back to the name-only
    heuristic. All names + the folder-derived title are Markdown-escaped.
    """
    title, date_line = _parse_header(folder)

    # Stable, human-friendly order: real names first (alphabetical), then anonymous.
    def _is_anon(entry: dict) -> bool:
        return _entry_is_anonymous(entry, anonymous_pids)

    named = [p for p in participants if str(p.get("name", "")).strip()]
    real = sorted((p for p in named if not _is_anon(p)), key=lambda p: str(p["name"]).lower())
    anon = sorted((p for p in named if _is_anon(p)), key=lambda p: str(p["name"]).lower())

    lines: list[str] = []
    lines.append(f"# Attendance — {_md_escape(title)}")
    lines.append("")
    if date_line:
        lines.append(f"_Date: {date_line}_")
    if gdrive_url:
        lines.append(f"_Materials: {gdrive_url}_")
    if date_line or gdrive_url:
        lines.append("")

    total = len(real) + len(anon)
    if total == 0:
        lines.append("_No attendees yet._")
        lines.append("")
        return "\n".join(lines) + "\n"

    idx = 1
    for p in real:
        lines.append(f"{idx}. {_md_escape(p['name'])}")
        idx += 1
    for p in anon:
        # Italic + explicit tag makes anonymous entries distinguishable.
        lines.append(f"{idx}. _{_md_escape(p['name'])}_ (anonymous)")
        idx += 1

    lines.append("")
    summary = f"**{total}** attendee{'s' if total != 1 else ''}"
    if anon:
        summary += f" ({len(anon)} anonymous)"
    lines.append(summary)
    lines.append("")
    return "\n".join(lines) + "\n"


def _target_path(folder: Path) -> Path:
    return folder / ATTENDEES_FILENAME


def regenerate_attendees(folder: Path | None = None, gdrive_url: str | None = None) -> Path | None:
    """Fully regenerate `attendees.md` from the live roster. Returns the path written.

    No-op (returns None) when there is no active session folder on disk.
    """
    from daemon.files_md import atomic_write
    from daemon.host_state_router import _build_host_participants_list

    if folder is None:
        from daemon.misc.content_files import get_active_session_folder

        folder = get_active_session_folder()
    if folder is None:
        return None

    if gdrive_url is None:
        try:
            from daemon.session import state as session_shared_state

            gdrive_url = session_shared_state.get_gdrive_url()
        except Exception:
            gdrive_url = None

    from daemon.participant.state import participant_state

    participants = _build_host_participants_list()
    text = render_attendees_md(
        folder,
        participants,
        gdrive_url,
        anonymous_pids=set(participant_state.anonymous_pids),
    )
    target = _target_path(folder)
    atomic_write(target, text)
    return target
