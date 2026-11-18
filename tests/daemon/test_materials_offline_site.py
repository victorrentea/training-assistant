"""The open-from-disk copy of the participant site (daemon/materials/offline_site.py)."""
import io
import json
import re
import types
import zipfile
from pathlib import Path

import pytest

from daemon.materials import offline_copy
from daemon.materials.offline_copy import OfflineCopyPublisher, write_drive_zip
from daemon.materials.offline_site import (
    OfflineDeck,
    build_site,
    capture_snapshot,
    fingerprint,
    site_zip,
)
from daemon.materials.zip_builder import build_session_zip

STATE = {
    "session_name": "2026-11-18 AI@Somewhere",
    "my_name": "Alice",
    "slides_current": {"slug": "deck", "page": 12},
    "attention_enabled": True,
    "notes_updated_at": "2026-11-18T10:00:00+00:00",
    "wiki_updated_at": "2026-11-18T11:00:00+00:00",
    "gdrive_url": "https://drive.example.test/folder",
}
ANSWERS = {"state": STATE, "notes": {"notes_content": "WiFi: 1234"}, "summary": {"points": []}}


def _fetch(path):
    answer = ANSWERS.get(path)
    return json.loads(json.dumps(answer)) if answer else None


def _data(files) -> dict:
    return json.loads(files["offline-data.js"].decode("utf-8").removeprefix("window.__OFFLINE__ = "))


def _wiki_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("Somewhere wiki/index.html", "<html>wiki</html>")
        archive.writestr("Somewhere wiki/notes/a.html", "<html>a</html>")
    return buffer.getvalue()


def test_snapshot_keeps_content_and_drops_the_live_moment():
    api = capture_snapshot(_fetch)

    assert set(api) == {"state", "notes", "summary"}  # no agenda today: left out
    assert api["notes"]["notes_content"] == "WiFi: 1234"
    assert api["state"]["slides_current"] is None
    assert api["state"]["attention_enabled"] is False
    assert api["state"]["my_name"] == ""
    assert api["state"]["gdrive_url"] == STATE["gdrive_url"]


def test_page_references_only_files_inside_the_copy():
    files = build_site(capture_snapshot(_fetch), session_name="S")
    html = files["index.html"].decode("utf-8")

    assert html.index("offline.js") < html.index("theme.js"), "the shim must run before the page's scripts"
    assert '"/static/' not in html
    for ref in re.findall(r'(?:src|href)="(static/[^"?]+)', html):
        assert ref in files, f"{ref} is referenced but not in the copy"
    assert "static/vendor/fonts/material-symbols-outlined.woff2" in files


def test_a_new_cdn_library_in_the_page_must_be_bundled():
    """Opened from disk, possibly with no network: every library the page needs to render
    its content travels with the copy. pdf.js and html2canvas serve only the live slides
    view and the bug report, both off in the copy."""
    html = build_site(capture_snapshot(_fetch), session_name="S")["index.html"].decode("utf-8")
    external = set(re.findall(r'<script[^>]+src="(https?://[^"]+)"', html))

    assert external == set(), (
        f"participant.html loads {external} from a CDN: bundle it in "
        "daemon/materials/offline/vendor and list it in offline_site._CDN"
    )


def test_decks_link_to_the_pdfs_next_to_the_copy():
    files = build_site(
        capture_snapshot(_fetch),
        session_name="S",
        decks=[OfflineDeck(title="Agentic", filename="Agentic.pdf")],
    )

    assert _data(files)["decks"] == [
        {"title": "Agentic", "filename": "Agentic.pdf", "href": "../slides/Agentic.pdf"}
    ]


def test_wiki_entry_only_when_the_wiki_travels_along():
    without = build_site(capture_snapshot(_fetch), session_name="S")
    with_wiki = build_site(capture_snapshot(_fetch), session_name="S", wiki_site_zip=_wiki_zip())

    assert _data(without)["api"]["state"]["wiki_updated_at"] is None
    assert _data(with_wiki)["api"]["state"]["wiki_updated_at"] == STATE["wiki_updated_at"]
    assert with_wiki["wiki/index.html"] == b"<html>wiki</html>"
    assert with_wiki["wiki/notes/a.html"] == b"<html>a</html>"


def test_session_zip_takes_extra_files(tmp_path):
    (tmp_path / "notes.txt").write_text("n", encoding="utf-8")
    (tmp_path / "interact.zip").write_bytes(b"PK")  # the Drive copy is not zipped again

    payload = build_session_zip(tmp_path, {"interact/index.html": b"<html>"})

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert sorted(archive.namelist()) == ["interact/index.html", "notes.txt"]


def test_drive_zip_is_rewritten_only_when_the_content_differs(tmp_path):
    from datetime import datetime

    first = build_site(capture_snapshot(_fetch), session_name="S", saved_at=datetime(2026, 11, 18, 10))
    later = build_site(capture_snapshot(_fetch), session_name="S", saved_at=datetime(2026, 11, 18, 17))
    changed = build_site({**capture_snapshot(_fetch), "notes": {"notes_content": "more"}}, session_name="S")

    assert fingerprint(first) == fingerprint(later) != fingerprint(changed)
    assert write_drive_zip(tmp_path, first) is True
    assert write_drive_zip(tmp_path, later) is False
    assert write_drive_zip(tmp_path, changed) is True
    with zipfile.ZipFile(tmp_path / "interact.zip") as archive:
        assert "interact/index.html" in archive.namelist()
    assert [p.name for p in tmp_path.iterdir()] == ["interact.zip"]


def test_publisher_waits_until_the_session_has_gone_quiet(tmp_path):
    state = {"notes_updated_at": "1"}
    files = build_site(capture_snapshot(_fetch), session_name="S")
    publisher = OfflineCopyPublisher(site=lambda: files, state=lambda: dict(state))
    target = tmp_path / "interact.zip"

    publisher.check(tmp_path, 0)      # first sight
    publisher.check(tmp_path, 300)    # unchanged, but not for long enough
    assert not target.exists()
    state["notes_updated_at"] = "2"
    publisher.check(tmp_path, 590)    # still being edited: the wait starts over
    publisher.check(tmp_path, 900)
    assert not target.exists()
    publisher.check(tmp_path, 590 + offline_copy.SETTLE_S)
    assert target.exists()

    written = target.stat().st_mtime_ns
    publisher.check(tmp_path, 5000)   # nothing new: left alone
    assert target.stat().st_mtime_ns == written


def test_site_zip_opens(tmp_path):
    files = build_site(capture_snapshot(_fetch), session_name="S")
    with zipfile.ZipFile(io.BytesIO(site_zip(files))) as archive:
        assert archive.testzip() is None
        assert "interact/offline.js" in archive.namelist()
