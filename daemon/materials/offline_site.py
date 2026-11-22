"""The participant site as a read-only copy that opens from disk, for after the session.

"How long will Interact stay online?" — it does not need to: this freezes what a participant
sees (notes, summary, wiki, opened files, prompts, the last activity) into plain files.
`static/participant.html` is used as is; `offline/shim.js`, loaded first in its <head>,
answers the page's requests from the snapshot bundled next to it and turns the live-only
parts off. Same idea as the wiki's own download (daemon/wiki/downloads.py).

Two places get it:
- the materials zip a participant downloads, as its `interact/` folder
  (daemon/materials/upload.py), next to the `slides/` Railway adds;
- the session folder, as `interact.zip`, so it also reaches whoever opens the Google Drive
  folder later. That one has no deck PDFs: they are not in the session folder.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

_HERE = Path(__file__).resolve().parent
_OFFLINE_DIR = _HERE / "offline"
_STATIC_DIR = _HERE.parent.parent / "static"

SITE_DIR = "interact"
DRIVE_ZIP = "interact.zip"
PAGE = "index.html"

# What the page fetches on load and when a tab is opened; the key is the path after
# /api/participant/. A missing answer (no agenda today) is simply left out.
SNAPSHOT_PATHS = ("state", "agenda", "notes", "summary", "files-md", "prompts")

# The libraries participant.html takes from a CDN, bundled so the copy needs no network.
_CDN = {
    "https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.3/dist/confetti.browser.min.js": "confetti.browser.min.js",
    "https://cdn.jsdelivr.net/npm/mammoth@1/mammoth.browser.min.js": "mammoth.browser.min.js",
    "https://cdn.jsdelivr.net/npm/marked@9/marked.min.js": "marked.min.js",
}
_VENDOR = "static/vendor/offline"
_STATIC_REF = re.compile(r'(src|href)="/static/([^"?]+)(\?[^"]*)?"')
# Subsets the participant page never uses.
_SKIPPED_FONTS = ("talk-subset",)

# State that describes the live moment, not the content: a copy must not open on
# "the trainer is on slide 12" or ask for a reaction.
_LIVE_STATE = {
    "slides_current": None,
    "summary_scroll": None,
    "wiki_note": None,
    "attention_enabled": False,
    "slides_seen": None,
    "my_name": "",
    "my_score": 0,
    "my_score_token": "",
    "wiki_my_stars": [],
    "wiki_done": False,
}


class OfflineDeck(BaseModel):
    """A deck PDF the copy links to (it opens in the browser's own PDF viewer)."""

    title: str
    filename: str


Fetch = Callable[[str], dict | None]


def capture_snapshot(fetch: Fetch) -> dict[str, dict]:
    """The answers the page will ask for, taken from the daemon's own participant API."""
    api: dict[str, dict] = {}
    for path in SNAPSHOT_PATHS:
        answer = fetch(path)
        if answer is not None:
            api[path] = answer
    state = api.get("state")
    if state is not None:
        state.update(_LIVE_STATE)
    return api


def build_site(
    api: dict[str, dict],
    *,
    session_name: str,
    decks: list[OfflineDeck] | None = None,
    decks_href: str = "../slides/",
    wiki_site_zip: bytes | None = None,
    saved_at: datetime | None = None,
    static_dir: Path = _STATIC_DIR,
) -> dict[str, bytes]:
    """The files of the copy, by path inside it. `decks_href` is where the PDFs sit
    relative to the page; no decks, no Slides entry."""
    files: dict[str, bytes] = {}
    html = (static_dir / "participant.html").read_text(encoding="utf-8")

    for ref in sorted({m.group(2) for m in _STATIC_REF.finditer(html)}):
        source = static_dir / ref
        if source.is_file():
            files[f"static/{ref}"] = source.read_bytes()
    fonts = static_dir / "vendor" / "fonts"
    for font in sorted(fonts.glob("*.woff2")):
        if not any(skipped in font.name for skipped in _SKIPPED_FONTS):
            files[f"static/vendor/fonts/{font.name}"] = font.read_bytes()
    html = _STATIC_REF.sub(lambda m: f'{m.group(1)}="static/{m.group(2)}"', html)

    for url, name in _CDN.items():
        if url not in html:
            raise OfflineSiteError(f"participant.html no longer loads {url}")
        html = html.replace(url, f"{_VENDOR}/{name}")
        files[f"{_VENDOR}/{name}"] = (_OFFLINE_DIR / "vendor" / name).read_bytes()

    wiki = _unpack_wiki(wiki_site_zip, files) if wiki_site_zip else False
    if not wiki and "state" in api:
        api = {**api, "state": {**api["state"], "wiki_updated_at": None}}

    data = {
        "api": api,
        "session": session_name,
        "saved": (saved_at or datetime.now()).strftime("%Y-%m-%d %H:%M"),
        "decks": [
            {"title": d.title, "filename": d.filename, "href": decks_href + d.filename}
            for d in (decks or [])
        ],
        "wiki": wiki,
    }
    # "</script" cannot occur in a .js file's own text, but U+2028/9 end a JS line.
    payload = json.dumps(data, ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    files[_DATA_FILE] = f"{_DATA_PREFIX}{payload}\n".encode("utf-8")
    files["offline.js"] = (_OFFLINE_DIR / "shim.js").read_bytes()
    files["offline.css"] = (_OFFLINE_DIR / "offline.css").read_bytes()

    head = (
        f'<head><script src="{_DATA_FILE}"></script><script src="offline.js"></script>'
        '<link rel="stylesheet" href="offline.css"/>'
    )
    if "<head>" not in html:
        raise OfflineSiteError("participant.html has no <head> to hook into")
    files[PAGE] = html.replace("<head>", head, 1).encode("utf-8")
    return files


class OfflineSiteError(RuntimeError):
    """The page changed in a way the copy cannot follow; the materials still ship without it."""


def _unpack_wiki(site_zip: bytes, files: dict[str, bytes]) -> bool:
    """The wiki's own open-from-disk download, as the copy's wiki/ folder."""
    try:
        with zipfile.ZipFile(io.BytesIO(site_zip)) as archive:
            names = [n for n in archive.namelist() if not n.endswith("/")]
            if not names:
                return False
            root = names[0].split("/", 1)[0] + "/"
            if not all(n.startswith(root) for n in names) or f"{root}index.html" not in names:
                return False
            for name in names:
                files[f"wiki/{name[len(root):]}"] = archive.read(name)
    except zipfile.BadZipFile:
        return False
    return True


def wiki_site_zip_of(published_site: bytes | None) -> bytes | None:
    """The open-from-disk wiki inside the site last published to Railway, if any."""
    if not published_site:
        return None
    from daemon.wiki.downloads import DOWNLOADS_DIR, SITE_ZIP

    try:
        with zipfile.ZipFile(io.BytesIO(published_site)) as archive:
            return archive.read(f"{DOWNLOADS_DIR}/{SITE_ZIP}")
    except (KeyError, zipfile.BadZipFile):
        return None


def site_zip(files: dict[str, bytes], root: str = SITE_DIR, comment: bytes = b"") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        add_to_archive(archive, files, root)
        archive.comment = comment
    return buffer.getvalue()


# In the data, what changes without the content changing: when the copy was made, and
# the wiki's publish time, which moves at every daemon restart.
_DATA_FILE = "offline-data.js"
_DATA_PREFIX = "window.__OFFLINE__ = "


def fingerprint(files: dict[str, bytes]) -> str:
    """The same for two copies a reader could not tell apart."""
    digest = hashlib.sha256()
    for path in sorted(files):
        content = files[path]
        if path == _DATA_FILE:
            data = json.loads(content.decode("utf-8")[len(_DATA_PREFIX):])
            data.pop("saved", None)
            (data.get("api", {}).get("state") or {}).pop("wiki_updated_at", None)
            content = json.dumps(data, sort_keys=True).encode("utf-8")
        digest.update(path.encode("utf-8") + b"\0" + hashlib.sha256(content).digest())
    return digest.hexdigest()


def add_to_archive(archive: zipfile.ZipFile, files: dict[str, bytes], root: str = SITE_DIR) -> None:
    for path in sorted(files):
        # Fonts are compressed already.
        method = zipfile.ZIP_STORED if path.endswith(".woff2") else zipfile.ZIP_DEFLATED
        archive.writestr(f"{root}/{path}", files[path], compress_type=method)
