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

from pathlib import Path

ATTENDEES_FILENAME = "attendees.md"


def _fictional_names() -> frozenset[str]:
    """Names the daemon can auto-assign — used to flag anonymous attendees.

    A name from either fictional pool is treated as an anonymous / auto-assigned
    entry rather than a confirmed real name. This is a heuristic (a real person
    literally named "Frodo" would be flagged), acceptable for phase 1.
    """
    from daemon.participant.names import CHARACTER_NAMES, LOTR_NAMES

    return frozenset(LOTR_NAMES) | frozenset(n for n, _u in CHARACTER_NAMES)


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
) -> str:
    """Render the whole `attendees.md` from the live roster (full regeneration)."""
    title, date_line = _parse_header(folder)
    fictional = _fictional_names()

    # Stable, human-friendly order: real names first (alphabetical), then anonymous.
    def _is_anon(entry: dict) -> bool:
        return str(entry.get("name", "")) in fictional

    named = [p for p in participants if str(p.get("name", "")).strip()]
    real = sorted((p for p in named if not _is_anon(p)), key=lambda p: str(p["name"]).lower())
    anon = sorted((p for p in named if _is_anon(p)), key=lambda p: str(p["name"]).lower())

    lines: list[str] = []
    lines.append(f"# Attendance — {title}")
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
        lines.append(f"{idx}. {p['name']}")
        idx += 1
    for p in anon:
        # Italic + explicit tag makes anonymous entries distinguishable.
        lines.append(f"{idx}. _{p['name']}_ (anonymous)")
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

    participants = _build_host_participants_list()
    text = render_attendees_md(folder, participants, gdrive_url)
    target = _target_path(folder)
    atomic_write(target, text)
    return target


def init_attendees(folder: Path | None, gdrive_url: str | None = None) -> Path | None:
    """Create / reset `attendees.md` for a freshly (re)initialized session.

    Writes a clean file with an empty roster so a new session never carries
    stale attendees from a previous one.
    """
    from daemon.files_md import atomic_write

    if folder is None:
        return None
    text = render_attendees_md(folder, [], gdrive_url)
    target = _target_path(folder)
    atomic_write(target, text)
    return target
