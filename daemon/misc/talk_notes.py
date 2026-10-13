"""The trainer's notes file, mirrored live onto the talk phones.

VS Code (the victor-vsc extension) reports the notes file it has open: cursor
line, selection, which regions are folded, and the text whenever it changed.
Only the CURRENT session's notes file is shared; any other file is ignored.
Phones that follow the trainer scroll to his line and switch between the slides
and the notes as he does (`presenter_view`).
"""
from __future__ import annotations

from pathlib import Path

from daemon.misc.content_files import get_active_session_folder
from daemon.misc.state import misc_state
from daemon.participant.state import participant_state
from daemon.session_state import find_notes_in_folder
from daemon.ws_messages import PresenterViewMsg, TalkNotesMsg, TalkNotesReport
from daemon.ws_publish import broadcast


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def is_session_notes(path: str) -> bool:
    """True when `path` is the notes file of the active session."""
    folder = get_active_session_folder()
    notes = find_notes_in_folder(folder) if folder is not None else None
    return notes is not None and _same_file(Path(path), notes)


def _is_talk() -> bool:
    return participant_state.mode == "talk"


def set_presenter_view(view: str) -> None:
    """Record what the trainer presents from; tell the phones when it changes."""
    if misc_state.presenter_view == view:
        return
    misc_state.presenter_view = view
    if _is_talk():
        broadcast(PresenterViewMsg(view=view))


def apply_report(report: TalkNotesReport) -> dict:
    """Take one report from VS Code. Returns {tracked, need_text}."""
    if not is_session_notes(report.path):
        return {"tracked": False, "need_text": False}
    current = misc_state.talk_notes
    if current is None and report.text is None:
        # A daemon restart lost the text; VS Code sends it with the next report.
        return {"tracked": True, "need_text": True}
    cursor = report.model_dump(include={"line", "selection", "collapsed"})
    text_changed = report.text is not None and (current is None or current["text"] != report.text)
    revision = (current["revision"] if current else 0) + (1 if text_changed else 0)
    updated = {"revision": revision, "text": report.text if text_changed else current["text"], **cursor}
    changed = current is None or text_changed or any(current[k] != updated[k] for k in cursor)
    misc_state.talk_notes = updated
    if changed and _is_talk():
        broadcast(TalkNotesMsg(revision=revision, text=report.text if text_changed else None, **cursor))
    if report.focused:
        set_presenter_view("notes")
    return {"tracked": True, "need_text": False}
