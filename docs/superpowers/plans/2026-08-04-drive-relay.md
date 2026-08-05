> **STATUS: ABANDONED — 2026-08-05.** The feature this plan builds was removed the
> same day it shipped. See the design doc's status banner for why:
> `docs/superpowers/specs/2026-08-04-drive-relay-zip-design.md`.

# Google Drive Relay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a workshop participant paste a Google Drive folder link on
`interact.victorrentea.ro/drive` and receive a zip of that folder, without their
browser ever contacting Google and without the trainer's daemon being online.

**Architecture:** A self-contained `railway/features/drive_relay/` package. Layers, from
the inside out: `link_parser` (URL → Drive id), `drive_client` (Drive API v3 over stdlib
`urllib`), `ownership` (anti-abuse gate), `tree` (folder → flat transfer plan),
`zip_stream` (plan → zip bytes), `router` (HTTP). Nothing depends on the daemon,
session state, or WebSockets.

**Tech Stack:** Python 3.9+, FastAPI, Pydantic, stdlib `urllib.request` + `zipfile`,
pytest, plain HTML + vanilla JS.

**Spec:** `docs/superpowers/specs/2026-08-04-drive-relay-zip-design.md`

## Global Constraints

- **No new runtime dependency.** `railway/` runtime deps are exactly: fastapi,
  python-multipart, prometheus-fastapi-instrumentator, uvicorn[standard], websockets.
  Use stdlib `urllib.request` (as `railway/features/slides/cache.py:184` already does)
  and stdlib `zipfile`.
- **Nothing on disk**, not even ephemeral `/tmp`. Everything streams.
- **The participant's browser never contacts Google.** No 3xx response pointing at a
  Google host, no Drive link/thumbnail/iframe in the page, no new Google host in the CSP.
- **Works with the daemon offline**, with no active session, and with a *different*
  session active. No import of session state or daemon plumbing in this package.
- `MAX_TRANSFER_BYTES = 500 * 1024 * 1024`.
- **All UI-visible text in English.** Exact copy strings are given in Task 8 and Task 9;
  use them verbatim.
- All code, comments, and commit messages in English.
- Routes must be registered **before** the `/{session_id}` catch-all in `railway/app.py`.
- `openapi.json` is contract-tested (`tests/openapi/test_contract.py`). Every task that
  adds or changes a route must regenerate it.
- Ruff config: line-length 100, target py39 — so no `match`, and use
  `Optional[X]`-compatible syntax only where `from __future__ import annotations` is
  present (add it at the top of every new module).

---

### Task 1: Ownership spike — discover which identity fields Drive returns

This is the only task that needs Victor. It decides configuration, not architecture:
the code written in Task 4 handles all outcomes. Do it first so the answer is known
before deployment, but do not block Tasks 2–11 on it.

**Files:**
- Modify: `docs/superpowers/specs/2026-08-04-drive-relay-zip-design.md` (record findings)

- [ ] **Step 1: Ask Victor for a Google Drive API key and a sample folder**

He needs to: create a Google Cloud project → enable the Drive API → create an API key
→ restrict it *by API* (Drive only), **not** by HTTP referrer, since calls are
server-side. Then give you the key and the URL of one of his "anyone with the link"
course folders.

- [ ] **Step 2: Probe the metadata endpoint**

```bash
KEY='<api key>'
ID='<folder id from the pasted URL>'
curl -s "https://www.googleapis.com/drive/v3/files/$ID?fields=id,name,mimeType,owners(emailAddress,permissionId,displayName)&key=$KEY" | python3 -m json.tool
```

- [ ] **Step 3: Probe the listing endpoint**

```bash
curl -s "https://www.googleapis.com/drive/v3/files?q='$ID'+in+parents+and+trashed+%3D+false&fields=files(id,name,mimeType,size)&key=$KEY" | python3 -m json.tool
```

- [ ] **Step 4: Record the outcome in the spec**

Replace the "Open risk and its resolution" section's three bullets with what actually
came back, and state the chosen configuration:

- `owners[].emailAddress` populated → `DRIVE_OWNER_EMAILS=victorrentea@gmail.com`
- only `owners[].permissionId` → `DRIVE_OWNER_PERMISSION_IDS=<the id>`
- nothing identifying → the fallback: `DRIVE_ALLOWED_ROOT_IDS=<root folder ids>`, and
  add a Task 5b to `tree.py` that walks `parents` upward and rejects anything not
  descended from an allowed root.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-08-04-drive-relay-zip-design.md
git commit -m "docs: record Drive ownership field findings from API-key spike"
```

---

### Task 2: Link parser

**Files:**
- Create: `railway/features/drive_relay/__init__.py` (empty)
- Create: `railway/features/drive_relay/link_parser.py`
- Test: `tests/features/drive_relay/__init__.py` (empty), `tests/features/drive_relay/test_link_parser.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `parse_drive_url(url: str) -> str` — returns the Drive file id.
  - `class InvalidDriveLink(ValueError)`.

The id charset is restricted to `[A-Za-z0-9_-]` here. That is not cosmetic: the id is
interpolated into the Drive `q=` query in Task 3, and this is what stops a quote from
escaping into that query.

- [ ] **Step 1: Write the failing tests**

```python
# tests/features/drive_relay/test_link_parser.py
import pytest

from railway.features.drive_relay.link_parser import InvalidDriveLink, parse_drive_url

FOLDER_ID = "1A2b3C4d5E6f7G8h9I0jKlMnOpQrStUv"


@pytest.mark.parametrize("url", [
    f"https://drive.google.com/drive/folders/{FOLDER_ID}",
    f"https://drive.google.com/drive/folders/{FOLDER_ID}?usp=sharing",
    f"https://drive.google.com/drive/folders/{FOLDER_ID}?usp=drive_link&hl=ro",
    f"https://drive.google.com/drive/u/0/folders/{FOLDER_ID}",
    f"https://drive.google.com/drive/u/2/folders/{FOLDER_ID}",
    f"https://drive.google.com/file/d/{FOLDER_ID}/view?usp=sharing",
    f"https://drive.google.com/open?id={FOLDER_ID}",
    f"https://docs.google.com/document/d/{FOLDER_ID}/edit",
    f"https://docs.google.com/spreadsheets/d/{FOLDER_ID}/edit#gid=0",
    f"https://docs.google.com/presentation/d/{FOLDER_ID}/edit",
    f"  https://drive.google.com/drive/folders/{FOLDER_ID}  ",
])
def test_extracts_id_from_every_supported_shape(url):
    assert parse_drive_url(url) == FOLDER_ID


@pytest.mark.parametrize("url", [
    "",
    "   ",
    "not a url",
    "https://example.com/drive/folders/abc",
    "https://drive.google.com/drive/folders/",
    "https://drive.google.com/drive/folders/short",
    "https://evil.com/?x=https://drive.google.com/drive/folders/" + FOLDER_ID,
    f"https://drive.google.com/drive/folders/{FOLDER_ID}'+or+'1'%3d'1",
])
def test_rejects_anything_else(url):
    with pytest.raises(InvalidDriveLink):
        parse_drive_url(url)


def test_rejects_id_with_quote_so_it_cannot_escape_the_drive_query():
    with pytest.raises(InvalidDriveLink):
        parse_drive_url("https://drive.google.com/drive/folders/abc'def'ghij")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_link_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'railway.features.drive_relay'`

- [ ] **Step 3: Write the implementation**

```python
# railway/features/drive_relay/link_parser.py
"""Turn a pasted Google Drive URL into a Drive file id.

Pure string work, no I/O. The id charset is deliberately narrow: Task 3
interpolates the id into Drive's ``q=`` query, and rejecting anything outside
``[A-Za-z0-9_-]`` here is what keeps a quote from escaping into that query.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

_ID = r"[A-Za-z0-9_-]{10,}"

# Ordered by how often participants paste them.
_PATH_PATTERNS = (
    re.compile(rf"^/drive/folders/({_ID})$"),
    re.compile(rf"^/drive/u/\d+/folders/({_ID})$"),
    re.compile(rf"^/file/d/({_ID})(?:/.*)?$"),
    re.compile(rf"^/(?:document|spreadsheets|presentation)/d/({_ID})(?:/.*)?$"),
)

_ALLOWED_HOSTS = frozenset({"drive.google.com", "docs.google.com"})


class InvalidDriveLink(ValueError):
    """The pasted text is not a Google Drive link we can act on."""


def parse_drive_url(url: str) -> str:
    """Return the Drive file id in ``url``.

    Raises InvalidDriveLink for anything that is not a recognised Drive URL on a
    Google host. We match known shapes rather than scanning for the first
    id-looking substring, so a link that merely *mentions* a Drive id in a query
    parameter is rejected instead of silently trusted.
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or parsed.hostname not in _ALLOWED_HOSTS:
        raise InvalidDriveLink(url)

    path = parsed.path.rstrip("/") or "/"
    for pattern in _PATH_PATTERNS:
        match = pattern.match(path)
        if match:
            return match.group(1)

    if path == "/open":
        candidates = parse_qs(parsed.query).get("id", [])
        if candidates and re.fullmatch(_ID, candidates[0]):
            return candidates[0]

    raise InvalidDriveLink(url)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_link_parser.py -v`
Expected: PASS (23 tests)

- [ ] **Step 5: Commit**

```bash
git add railway/features/drive_relay/ tests/features/drive_relay/
git commit -m "feat(drive-relay): parse pasted Drive URLs into file ids"
```

---

### Task 3: Drive API client

**Files:**
- Create: `railway/features/drive_relay/drive_client.py`
- Test: `tests/features/drive_relay/test_drive_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `@dataclass(frozen=True) class DriveOwner: email: str; permission_id: str; display_name: str`
  - `@dataclass(frozen=True) class DriveFile: id: str; name: str; mime_type: str; size: Optional[int]; owners: Tuple[DriveOwner, ...]; shortcut_target_id: Optional[str]`
  - `class DriveError(RuntimeError)` with attribute `status: int`
  - `get_metadata(file_id: str) -> DriveFile`
  - `list_children(folder_id: str) -> List[DriveFile]` (follows `nextPageToken`)
  - `open_download(file: DriveFile) -> Iterator[bytes]`
  - `archive_name(file: DriveFile) -> str`
  - `is_folder(file: DriveFile) -> bool`, `is_shortcut(file: DriveFile) -> bool`, `is_native(file: DriveFile) -> bool`
  - `FOLDER_MIME`, `SHORTCUT_MIME`, `NATIVE_EXPORT_MIME` constants

- [ ] **Step 1: Write the failing tests**

```python
# tests/features/drive_relay/test_drive_client.py
import io
import json
import urllib.error

import pytest

from railway.features.drive_relay import drive_client as dc


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture(autouse=True)
def api_config(monkeypatch):
    monkeypatch.setenv("GOOGLE_DRIVE_API_KEY", "test-key")
    monkeypatch.setenv("DRIVE_API_BASE_URL", "https://drive.test/drive/v3")


def install_urlopen(monkeypatch, handler):
    """Route every urlopen call through `handler(url) -> bytes`, recording URLs."""
    calls = []

    def fake_urlopen(request, **kwargs):
        url = request.full_url
        calls.append(url)
        return FakeResponse(handler(url))

    monkeypatch.setattr(dc.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_get_metadata_calls_the_right_url(monkeypatch):
    payload = {"id": "abc", "name": "Materials", "mimeType": dc.FOLDER_MIME}
    calls = install_urlopen(monkeypatch, lambda url: json.dumps(payload).encode())

    dc.get_metadata("abc")

    assert calls[0].startswith("https://drive.test/drive/v3/files/abc?")
    assert "key=test-key" in calls[0]
    assert "owners%28emailAddress%2CpermissionId%2CdisplayName%29" in calls[0]


def test_get_metadata_parses_owners_and_size(monkeypatch):
    payload = {
        "id": "abc", "name": "Slides.pdf", "mimeType": "application/pdf", "size": "1234",
        "owners": [{"emailAddress": "v@example.com", "permissionId": "42",
                    "displayName": "Victor"}],
    }
    install_urlopen(monkeypatch, lambda url: json.dumps(payload).encode())

    file = dc.get_metadata("abc")

    assert file.id == "abc"
    assert file.name == "Slides.pdf"
    assert file.size == 1234
    assert file.owners[0].email == "v@example.com"
    assert file.owners[0].permission_id == "42"
    assert file.shortcut_target_id is None


def test_native_files_have_no_size(monkeypatch):
    payload = {"id": "d1", "name": "Notes", "mimeType": "application/vnd.google-apps.document"}
    install_urlopen(monkeypatch, lambda url: json.dumps(payload).encode())

    file = dc.get_metadata("d1")

    assert file.size is None
    assert dc.is_native(file) is True
    assert dc.archive_name(file) == "Notes.pdf"


def test_archive_name_leaves_binary_names_alone(monkeypatch):
    payload = {"id": "f1", "name": "Deck.pdf", "mimeType": "application/pdf", "size": "10"}
    install_urlopen(monkeypatch, lambda url: json.dumps(payload).encode())

    assert dc.archive_name(dc.get_metadata("f1")) == "Deck.pdf"


def test_list_children_follows_pagination(monkeypatch):
    pages = {
        1: {"files": [{"id": "a", "name": "A", "mimeType": "application/pdf", "size": "1"}],
            "nextPageToken": "TOKEN2"},
        2: {"files": [{"id": "b", "name": "B", "mimeType": "application/pdf", "size": "2"}]},
    }

    def handler(url):
        page = 2 if "pageToken=TOKEN2" in url else 1
        return json.dumps(pages[page]).encode()

    calls = install_urlopen(monkeypatch, handler)

    children = dc.list_children("folder1")

    assert [c.id for c in children] == ["a", "b"]
    assert len(calls) == 2
    assert "trashed" in calls[0]  # trashed items excluded at the query level


def test_http_error_becomes_drive_error_with_status(monkeypatch):
    def fake_urlopen(request, **kwargs):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(dc.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(dc.DriveError) as exc:
        dc.get_metadata("missing")
    assert exc.value.status == 404


def test_network_failure_becomes_502(monkeypatch):
    def fake_urlopen(request, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(dc.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(dc.DriveError) as exc:
        dc.get_metadata("abc")
    assert exc.value.status == 502


def test_missing_api_key_is_a_clear_failure(monkeypatch):
    monkeypatch.delenv("GOOGLE_DRIVE_API_KEY", raising=False)

    with pytest.raises(dc.DriveError) as exc:
        dc.get_metadata("abc")
    assert exc.value.status == 503


def test_binary_download_streams_chunks(monkeypatch):
    body = b"y" * (dc._CHUNK_BYTES + 7)
    urls = install_urlopen(monkeypatch, lambda url: body)
    file = dc.DriveFile(id="f1", name="a.bin", mime_type="application/octet-stream",
                        size=len(body), owners=(), shortcut_target_id=None)

    chunks = list(dc.open_download(file))

    assert b"".join(chunks) == body
    assert len(chunks) == 2
    assert "alt=media" in urls[0]


def test_native_download_uses_the_pdf_export_endpoint(monkeypatch):
    urls = install_urlopen(monkeypatch, lambda url: b"%PDF-1.4")
    file = dc.DriveFile(id="d1", name="Notes",
                        mime_type="application/vnd.google-apps.document",
                        size=None, owners=(), shortcut_target_id=None)

    assert b"".join(dc.open_download(file)) == b"%PDF-1.4"
    assert "/files/d1/export" in urls[0]
    assert "mimeType=application%2Fpdf" in urls[0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_drive_client.py -v`
Expected: FAIL — `ModuleNotFoundError: ... drive_client`

- [ ] **Step 3: Write the implementation**

```python
# railway/features/drive_relay/drive_client.py
"""Google Drive API v3 over stdlib urllib, authenticated with a plain API key.

The only module in this package that knows Google exists. API-key auth is enough
because every folder we serve is shared "anyone with the link" — see the spec.

urllib follows redirects on its own, which is load-bearing: large-file downloads
redirect to drive.usercontent.google.com and we must follow that *here*, on the
server, so the participant's browser never talks to Google.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
NATIVE_MIME_PREFIX = "application/vnd.google-apps."
NATIVE_EXPORT_MIME = "application/pdf"

_DEFAULT_BASE_URL = "https://www.googleapis.com/drive/v3"
_TIMEOUT_S = 30
_CHUNK_BYTES = 64 * 1024
_PAGE_SIZE = "1000"

_FILE_FIELDS = (
    "id,name,mimeType,size,owners(emailAddress,permissionId,displayName),"
    "shortcutDetails(targetId)"
)


@dataclass(frozen=True)
class DriveOwner:
    email: str
    permission_id: str
    display_name: str


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    size: Optional[int]
    owners: Tuple[DriveOwner, ...]
    shortcut_target_id: Optional[str]


class DriveError(RuntimeError):
    """A Drive call failed. ``status`` is the HTTP status we should surface."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _base_url() -> str:
    return os.environ.get("DRIVE_API_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")


def _api_key() -> str:
    key = os.environ.get("GOOGLE_DRIVE_API_KEY", "").strip()
    if not key:
        raise DriveError(503, "GOOGLE_DRIVE_API_KEY is not configured")
    return key


def _ssl_ctx() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _build_url(path: str, params: dict) -> str:
    query = urllib.parse.urlencode(dict(params, key=_api_key()))
    return f"{_base_url()}{path}?{query}"


def _open(url: str):
    request = urllib.request.Request(url, method="GET")
    try:
        return urllib.request.urlopen(request, context=_ssl_ctx(), timeout=_TIMEOUT_S)
    except urllib.error.HTTPError as exc:
        raise DriveError(exc.code, f"Drive returned {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise DriveError(502, f"Drive is unreachable: {exc}") from exc


def _get_json(path: str, params: dict) -> dict:
    with _open(_build_url(path, params)) as response:
        return json.loads(response.read().decode("utf-8"))


def _to_file(raw: dict) -> DriveFile:
    owners = tuple(
        DriveOwner(
            email=(owner.get("emailAddress") or "").strip().lower(),
            permission_id=(owner.get("permissionId") or "").strip(),
            display_name=(owner.get("displayName") or "").strip(),
        )
        for owner in raw.get("owners", [])
    )
    raw_size = raw.get("size")
    return DriveFile(
        id=raw.get("id", ""),
        name=raw.get("name", "") or "untitled",
        mime_type=raw.get("mimeType", ""),
        size=int(raw_size) if raw_size is not None else None,
        owners=owners,
        shortcut_target_id=(raw.get("shortcutDetails") or {}).get("targetId"),
    )


def is_folder(file: DriveFile) -> bool:
    return file.mime_type == FOLDER_MIME


def is_shortcut(file: DriveFile) -> bool:
    return file.mime_type == SHORTCUT_MIME


def is_native(file: DriveFile) -> bool:
    """True for Docs/Sheets/Slides — they have no bytes and must be exported."""
    return file.mime_type.startswith(NATIVE_MIME_PREFIX) and not is_folder(file) and not is_shortcut(file)


def archive_name(file: DriveFile) -> str:
    """The filename this file should carry inside the archive."""
    if is_native(file) and not file.name.lower().endswith(".pdf"):
        return f"{file.name}.pdf"
    return file.name


def get_metadata(file_id: str) -> DriveFile:
    path = f"/files/{urllib.parse.quote(file_id, safe='')}"
    return _to_file(_get_json(path, {"fields": _FILE_FIELDS, "supportsAllDrives": "true"}))


def list_children(folder_id: str) -> List[DriveFile]:
    """Every non-trashed direct child of ``folder_id``, across all result pages."""
    children: List[DriveFile] = []
    page_token = None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": f"nextPageToken,files({_FILE_FIELDS})",
            "pageSize": _PAGE_SIZE,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        payload = _get_json("/files", params)
        children.extend(_to_file(raw) for raw in payload.get("files", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            return children


def open_download(file: DriveFile) -> Iterator[bytes]:
    """Yield the file's bytes, exporting Google-native files to PDF."""
    quoted = urllib.parse.quote(file.id, safe="")
    if is_native(file):
        url = _build_url(f"/files/{quoted}/export", {"mimeType": NATIVE_EXPORT_MIME})
    else:
        url = _build_url(f"/files/{quoted}", {"alt": "media", "supportsAllDrives": "true"})

    with _open(url) as response:
        while True:
            chunk = response.read(_CHUNK_BYTES)
            if not chunk:
                return
            yield chunk
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_drive_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add railway/features/drive_relay/drive_client.py tests/features/drive_relay/test_drive_client.py
git commit -m "feat(drive-relay): Drive API v3 client on stdlib urllib"
```

---

### Task 4: Ownership gate

**Files:**
- Create: `railway/features/drive_relay/ownership.py`
- Test: `tests/features/drive_relay/test_ownership.py`

**Interfaces:**
- Consumes: `DriveFile`, `DriveOwner` from `drive_client`.
- Produces:
  - `is_owned_by_host(file: DriveFile, *, emails: frozenset, permission_ids: frozenset) -> bool`
  - `configured_identity() -> Tuple[frozenset, frozenset]` reading `DRIVE_OWNER_EMAILS`
    and `DRIVE_OWNER_PERMISSION_IDS` (comma-separated).

Matching on *any* populated identity field is deliberate: Task 1 may find that Google
redacts `emailAddress` for API-key requests, and `permissionId` is then the only
identity available.

- [ ] **Step 1: Write the failing tests**

```python
# tests/features/drive_relay/test_ownership.py
import pytest

from railway.features.drive_relay.drive_client import DriveFile, DriveOwner
from railway.features.drive_relay.ownership import configured_identity, is_owned_by_host

EMAILS = frozenset({"victorrentea@gmail.com"})
PERMISSION_IDS = frozenset({"1234567890"})


def make_file(owners):
    return DriveFile(id="f", name="n", mime_type="application/pdf", size=1,
                     owners=tuple(owners), shortcut_target_id=None)


def owner(email="", permission_id="", display_name=""):
    return DriveOwner(email=email, permission_id=permission_id, display_name=display_name)


def check(file):
    return is_owned_by_host(file, emails=EMAILS, permission_ids=PERMISSION_IDS)


def test_accepts_matching_email():
    assert check(make_file([owner(email="victorrentea@gmail.com")])) is True


def test_email_match_is_case_insensitive():
    assert check(make_file([owner(email="VictorRentea@Gmail.com")])) is True


def test_accepts_matching_permission_id_when_email_is_redacted():
    assert check(make_file([owner(permission_id="1234567890")])) is True


def test_rejects_a_stranger():
    assert check(make_file([owner(email="someone@else.com", permission_id="999")])) is False


def test_rejects_when_no_owner_information_is_available():
    assert check(make_file([])) is False


def test_rejects_owner_with_only_a_display_name():
    assert check(make_file([owner(display_name="Victor Rentea")])) is False


def test_accepts_when_any_of_several_owners_matches():
    file = make_file([owner(email="someone@else.com"), owner(email="victorrentea@gmail.com")])
    assert check(file) is True


def test_configured_identity_reads_and_normalises_env(monkeypatch):
    monkeypatch.setenv("DRIVE_OWNER_EMAILS", " Victor@Example.com , second@example.com ")
    monkeypatch.setenv("DRIVE_OWNER_PERMISSION_IDS", "111, 222")

    emails, permission_ids = configured_identity()

    assert emails == frozenset({"victor@example.com", "second@example.com"})
    assert permission_ids == frozenset({"111", "222"})


def test_configured_identity_is_empty_when_unset(monkeypatch):
    monkeypatch.delenv("DRIVE_OWNER_EMAILS", raising=False)
    monkeypatch.delenv("DRIVE_OWNER_PERMISSION_IDS", raising=False)

    assert configured_identity() == (frozenset(), frozenset())


def test_nothing_is_owned_when_nothing_is_configured():
    file = make_file([owner(email="victorrentea@gmail.com", permission_id="1234567890")])
    assert is_owned_by_host(file, emails=frozenset(), permission_ids=frozenset()) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_ownership.py -v`
Expected: FAIL — `ModuleNotFoundError: ... ownership`

- [ ] **Step 3: Write the implementation**

```python
# railway/features/drive_relay/ownership.py
"""The anti-abuse gate: only folders owned by the trainer may be relayed.

Without this, an endpoint that zips any public Drive folder is a free download
proxy for the whole internet.

Checked once, on the pasted id — files *inside* an approved folder are not
re-checked. If it sits in the trainer's folder, the trainer vouched for it, and
that correctly covers files other people placed there.

An owner matches on ANY populated identity field, because Google may redact
`emailAddress` for API-key requests and leave only `permissionId`. `displayName`
is never accepted — it is user-settable, so anyone could claim it.
"""
from __future__ import annotations

import os
from typing import FrozenSet, Tuple

from railway.features.drive_relay.drive_client import DriveFile


def _split_env(name: str, lowercase: bool) -> FrozenSet[str]:
    raw = os.environ.get(name, "")
    values = (part.strip() for part in raw.split(","))
    return frozenset(v.lower() if lowercase else v for v in values if v)


def configured_identity() -> Tuple[FrozenSet[str], FrozenSet[str]]:
    """(allowed owner emails, allowed owner permission ids) from the environment."""
    return (
        _split_env("DRIVE_OWNER_EMAILS", lowercase=True),
        _split_env("DRIVE_OWNER_PERMISSION_IDS", lowercase=False),
    )


def is_owned_by_host(
    file: DriveFile,
    *,
    emails: FrozenSet[str],
    permission_ids: FrozenSet[str],
) -> bool:
    """True when some owner of ``file`` is a configured trainer identity.

    Fails closed: no configuration, or no owner information from Drive, means no.
    """
    for owner in file.owners:
        if owner.email and owner.email.lower() in emails:
            return True
        if owner.permission_id and owner.permission_id in permission_ids:
            return True
    return False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_ownership.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add railway/features/drive_relay/ownership.py tests/features/drive_relay/test_ownership.py
git commit -m "feat(drive-relay): owner gate so the relay only serves the trainer's folders"
```

---

### Task 4b: Exclusion policy

Discovered during Task 1's spike: the session folders this relay serves carry
`session-state.json`, `attendees.md` and `.obsidian/` alongside the course materials.
`attendees.md` is the participant roster — it must not land in anyone's download.

**Files:**
- Create: `railway/features/drive_relay/exclusions.py`
- Test: `tests/features/drive_relay/test_exclusions.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `is_excluded_file(name: str) -> bool`
  - `is_excluded_dir(name: str) -> bool`

`*.zip` is deliberately NOT excluded — see the spec's Exclusions section.

- [ ] **Step 1: Write the failing tests**

```python
# tests/features/drive_relay/test_exclusions.py
import pytest

from railway.features.drive_relay.exclusions import is_excluded_dir, is_excluded_file


@pytest.mark.parametrize("name", [
    "session-state.json",
    "attendees.md",
    "Icon",
    "Icon\r",
    "~$Slides.pptx",
    "~$notes.docx",
])
def test_internal_files_are_excluded(name):
    assert is_excluded_file(name) is True


@pytest.mark.parametrize("name", [
    "Intro.pdf",
    "ai-summary.md",
    "opened-files.md",
    "Workshop - notes.txt",
    "session-state.json.bak",
    "my-attendees.md",
])
def test_course_materials_are_kept(name):
    assert is_excluded_file(name) is False


def test_zip_files_are_kept():
    """The daemon skips zips so its archive won't nest; the relay has no such problem."""
    assert is_excluded_file("wiki.zip") is False
    assert is_excluded_file("wiki-day1.zip") is False


def test_obsidian_directory_is_excluded():
    assert is_excluded_dir(".obsidian") is True


@pytest.mark.parametrize("name", ["uploads", "wiki", "Day 2", "obsidian"])
def test_content_directories_are_kept(name):
    assert is_excluded_dir(name) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_exclusions.py -v`
Expected: FAIL — `ModuleNotFoundError: ... exclusions`

- [ ] **Step 3: Write the implementation**

```python
# railway/features/drive_relay/exclusions.py
"""What never reaches a participant's download.

Session folders are mirrored to Drive as they are on disk, so they carry files
that exist for the tooling rather than for the audience — most importantly
attendees.md, which is the participant roster.

This deliberately duplicates most of daemon/materials/zip_builder.py instead of
importing it. The two answer different questions ("what goes into the archive I
build from the local folder" vs "what goes into the archive I relay from
Drive"), and they have already diverged: zip_builder skips *.zip so its own
archive will not swallow a previous one, while here wiki.zip is content the
participant actually wants.
"""
from __future__ import annotations

import fnmatch

# "Icon\r" is the real name of the macOS custom-folder-icon file; Finder and ls
# both render it as "Icon".
_EXCLUDED_NAMES = frozenset({"session-state.json", "attendees.md", "Icon", "Icon\r"})
_EXCLUDED_GLOBS = ("~$*",)
_EXCLUDED_DIRS = frozenset({".obsidian"})


def is_excluded_file(name: str) -> bool:
    """True when a file with this name must be kept out of the archive."""
    if name in _EXCLUDED_NAMES:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in _EXCLUDED_GLOBS)


def is_excluded_dir(name: str) -> bool:
    """True when a directory with this name must not be descended into."""
    return name in _EXCLUDED_DIRS
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_exclusions.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add railway/features/drive_relay/exclusions.py tests/features/drive_relay/test_exclusions.py
git commit -m "feat(drive-relay): keep internal session files out of participant downloads"
```

---

### Task 5: Transfer plan (folder traversal)

**Files:**
- Create: `railway/features/drive_relay/tree.py`
- Test: `tests/features/drive_relay/test_tree.py`

**Interfaces:**
- Consumes: `drive_client.list_children`, `drive_client.get_metadata`,
  `drive_client.archive_name`, `is_folder`, `is_shortcut`, `DriveFile`;
  `exclusions.is_excluded_file`, `exclusions.is_excluded_dir` (Task 4b).
- Produces:
  - `@dataclass(frozen=True) class PlannedEntry: archive_path: str; file: DriveFile`
  - `@dataclass(frozen=True) class TransferPlan: root_name: str; entries: Tuple[PlannedEntry, ...]; known_bytes: int; has_unsized_files: bool`
  - `build_plan(root: DriveFile) -> TransferPlan`
  - `MAX_DEPTH = 20`

`build_plan` calls `drive_client` at module level; tests monkeypatch
`tree.drive_client.list_children`, matching how the rest of this codebase tests
network-touching modules.

- [ ] **Step 1: Write the failing tests**

```python
# tests/features/drive_relay/test_tree.py
import pytest

from railway.features.drive_relay import tree
from railway.features.drive_relay.drive_client import FOLDER_MIME, SHORTCUT_MIME, DriveFile


def folder(id, name):
    return DriveFile(id=id, name=name, mime_type=FOLDER_MIME, size=None, owners=(),
                     shortcut_target_id=None)


def pdf(id, name, size=100):
    return DriveFile(id=id, name=name, mime_type="application/pdf", size=size, owners=(),
                     shortcut_target_id=None)


def doc(id, name):
    return DriveFile(id=id, name=name, mime_type="application/vnd.google-apps.document",
                     size=None, owners=(), shortcut_target_id=None)


def shortcut(id, name, target):
    return DriveFile(id=id, name=name, mime_type=SHORTCUT_MIME, size=None, owners=(),
                     shortcut_target_id=target)


@pytest.fixture
def drive(monkeypatch):
    """A fake Drive: {folder_id: [children]} plus {id: file} for shortcut targets."""
    tree_map, by_id = {}, {}
    monkeypatch.setattr(tree.drive_client, "list_children", lambda fid: tree_map.get(fid, []))
    monkeypatch.setattr(tree.drive_client, "get_metadata", lambda fid: by_id[fid])
    return tree_map, by_id


def test_single_file_plan_has_one_entry():
    plan = tree.build_plan(pdf("f1", "Deck.pdf", size=2048))

    assert plan.root_name == "Deck.pdf"
    assert [e.archive_path for e in plan.entries] == ["Deck.pdf"]
    assert plan.known_bytes == 2048
    assert plan.has_unsized_files is False


def test_nested_folders_keep_their_structure(drive):
    tree_map, _ = drive
    tree_map["root"] = [pdf("a", "Intro.pdf"), folder("sub", "Day 2")]
    tree_map["sub"] = [pdf("b", "Lab.pdf"), folder("deep", "Solutions")]
    tree_map["deep"] = [pdf("c", "Answer.pdf")]

    plan = tree.build_plan(folder("root", "Workshop"))

    assert [e.archive_path for e in plan.entries] == [
        "Intro.pdf", "Day 2/Lab.pdf", "Day 2/Solutions/Answer.pdf",
    ]
    assert plan.known_bytes == 300


def test_empty_folders_produce_no_entries(drive):
    tree_map, _ = drive
    tree_map["root"] = [folder("empty", "Nothing")]
    tree_map["empty"] = []

    assert tree.build_plan(folder("root", "Workshop")).entries == ()


def test_native_files_are_planned_as_pdf_and_flagged_unsized(drive):
    tree_map, _ = drive
    tree_map["root"] = [doc("d1", "Agenda")]

    plan = tree.build_plan(folder("root", "Workshop"))

    assert [e.archive_path for e in plan.entries] == ["Agenda.pdf"]
    assert plan.known_bytes == 0
    assert plan.has_unsized_files is True


def test_shortcuts_are_resolved_to_their_target(drive):
    tree_map, by_id = drive
    tree_map["root"] = [shortcut("s1", "Link to deck", "t1")]
    by_id["t1"] = pdf("t1", "RealDeck.pdf", size=500)

    plan = tree.build_plan(folder("root", "Workshop"))

    assert [e.archive_path for e in plan.entries] == ["RealDeck.pdf"]
    assert plan.known_bytes == 500


def test_duplicate_names_in_one_folder_are_disambiguated(drive):
    tree_map, _ = drive
    tree_map["root"] = [pdf("a", "Notes.pdf"), pdf("b", "Notes.pdf"), pdf("c", "Notes.pdf")]

    paths = [e.archive_path for e in tree.build_plan(folder("root", "W")).entries]

    assert paths == ["Notes.pdf", "Notes (2).pdf", "Notes (3).pdf"]


def test_same_name_in_different_folders_is_left_alone(drive):
    tree_map, _ = drive
    tree_map["root"] = [pdf("a", "Notes.pdf"), folder("sub", "Day 2")]
    tree_map["sub"] = [pdf("b", "Notes.pdf")]

    paths = [e.archive_path for e in tree.build_plan(folder("root", "W")).entries]

    assert paths == ["Notes.pdf", "Day 2/Notes.pdf"]


def test_path_separators_in_drive_names_cannot_escape_the_archive(drive):
    tree_map, _ = drive
    tree_map["root"] = [pdf("a", "../../etc/passwd"), pdf("b", "a/b.pdf")]

    paths = [e.archive_path for e in tree.build_plan(folder("root", "W")).entries]

    assert paths == ["......etc.passwd", "a.b.pdf"]
    assert not any(p.startswith("/") or ".." in p for p in paths)


def test_internal_session_files_are_dropped(drive):
    """A real session folder on Drive carries these; participants must not get them."""
    tree_map, _ = drive
    tree_map["root"] = [
        pdf("a", "ai-summary.md", 10),
        pdf("b", "attendees.md", 20),
        pdf("c", "session-state.json", 30),
        pdf("d", "wiki.zip", 40),
    ]

    plan = tree.build_plan(folder("root", "Workshop"))

    assert [e.archive_path for e in plan.entries] == ["ai-summary.md", "wiki.zip"]
    assert plan.known_bytes == 50  # excluded files must not count toward the cap


def test_excluded_directories_are_not_descended_into(drive):
    tree_map, _ = drive
    tree_map["root"] = [folder("obs", ".obsidian"), pdf("a", "Intro.pdf", 10)]
    tree_map["obs"] = [pdf("x", "workspace.json", 5)]

    plan = tree.build_plan(folder("root", "Workshop"))

    assert [e.archive_path for e in plan.entries] == ["Intro.pdf"]


def test_a_folder_cycle_terminates(drive):
    tree_map, _ = drive
    tree_map["root"] = [folder("loop", "Loop")]
    tree_map["loop"] = [folder("root", "Back"), pdf("a", "Real.pdf")]

    plan = tree.build_plan(folder("root", "Workshop"))

    assert [e.archive_path for e in plan.entries] == ["Loop/Real.pdf"]


def test_depth_is_bounded(drive):
    tree_map, _ = drive
    for depth in range(tree.MAX_DEPTH + 5):
        tree_map[f"f{depth}"] = [folder(f"f{depth + 1}", f"L{depth + 1}")]
    tree_map[f"f{tree.MAX_DEPTH + 5}"] = [pdf("deep", "TooDeep.pdf")]

    plan = tree.build_plan(folder("f0", "Root"))

    assert plan.entries == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_tree.py -v`
Expected: FAIL — `ModuleNotFoundError: ... tree`

- [ ] **Step 3: Write the implementation**

```python
# railway/features/drive_relay/tree.py
"""Flatten a Drive folder into an ordered list of archive entries.

Separated from streaming so the whole transfer can be inspected before a single
byte moves: that is what lets the size cap and the error messages fire *before*
the download starts rather than halfway through it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

from railway.features.drive_relay import drive_client, exclusions
from railway.features.drive_relay.drive_client import DriveFile

MAX_DEPTH = 20

# Drive names may contain anything, including "/" and "..". Archive paths must not.
_UNSAFE_IN_NAME = re.compile(r"[/\\]|\.\.")


@dataclass(frozen=True)
class PlannedEntry:
    archive_path: str
    file: DriveFile


@dataclass(frozen=True)
class TransferPlan:
    root_name: str
    entries: Tuple[PlannedEntry, ...]
    known_bytes: int
    has_unsized_files: bool


def _safe_name(name: str) -> str:
    return _UNSAFE_IN_NAME.sub(".", name).strip() or "untitled"


def _unique(name: str, taken: Set[str]) -> str:
    """Disambiguate 'Notes.pdf' → 'Notes (2).pdf' within a single folder."""
    if name not in taken:
        taken.add(name)
        return name
    stem, dot, extension = name.rpartition(".")
    if not dot:
        stem, extension = name, ""
    suffix = 2
    while True:
        candidate = f"{stem} ({suffix}){'.' + extension if extension else ''}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
        suffix += 1


def _resolve(file: DriveFile) -> DriveFile:
    """Follow a shortcut to the file it points at; other files pass through."""
    if not drive_client.is_shortcut(file) or not file.shortcut_target_id:
        return file
    return drive_client.get_metadata(file.shortcut_target_id)


def build_plan(root: DriveFile) -> TransferPlan:
    """Walk ``root`` and return every file that belongs in the archive.

    Guards against Drive's shortcut-induced cycles (a folder reachable from
    inside itself) and against pathological depth.
    """
    entries: List[PlannedEntry] = []
    known_bytes = 0
    has_unsized = False

    if not drive_client.is_folder(root):
        resolved = _resolve(root)
        name = _safe_name(drive_client.archive_name(resolved))
        return TransferPlan(
            root_name=resolved.name,
            entries=(PlannedEntry(archive_path=name, file=resolved),),
            known_bytes=resolved.size or 0,
            has_unsized_files=resolved.size is None,
        )

    visited: Set[str] = {root.id}
    stack: List[Tuple[DriveFile, str, int]] = [(root, "", 0)]

    while stack:
        folder, prefix, depth = stack.pop(0)
        if depth >= MAX_DEPTH:
            continue
        taken: Set[str] = set()
        pending_folders: List[Tuple[DriveFile, str, int]] = []

        for child in drive_client.list_children(folder.id):
            resolved = _resolve(child)
            if drive_client.is_folder(resolved):
                if resolved.id in visited or exclusions.is_excluded_dir(resolved.name):
                    continue
                visited.add(resolved.id)
                name = _unique(_safe_name(resolved.name), taken)
                pending_folders.append((resolved, f"{prefix}{name}/", depth + 1))
                continue

            if exclusions.is_excluded_file(resolved.name):
                continue

            name = _unique(_safe_name(drive_client.archive_name(resolved)), taken)
            entries.append(PlannedEntry(archive_path=f"{prefix}{name}", file=resolved))
            if resolved.size is None:
                has_unsized = True
            else:
                known_bytes += resolved.size

        stack.extend(pending_folders)

    return TransferPlan(
        root_name=root.name,
        entries=tuple(entries),
        known_bytes=known_bytes,
        has_unsized_files=has_unsized,
    )
```

Note on ordering: files of a folder are emitted before descending into its
subfolders (breadth-first by folder, depth-ordered by prefix), which is what the
`test_nested_folders_keep_their_structure` expectation encodes.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_tree.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add railway/features/drive_relay/tree.py tests/features/drive_relay/test_tree.py
git commit -m "feat(drive-relay): flatten a Drive folder into a transfer plan"
```

---

### Task 6: Streaming zip writer

**Files:**
- Create: `railway/features/drive_relay/zip_stream.py`
- Test: `tests/features/drive_relay/test_zip_stream.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (deliberately — it takes plain tuples).
- Produces:
  - `stream_zip(entries: Iterable[Tuple[str, Iterable[bytes]]], max_bytes: int) -> Iterator[bytes]`
  - `class TransferCapExceeded(RuntimeError)`

The approach was validated before adoption: memory stays flat (largest single yield
64 KB regardless of file size), and the output opens in Python's `zipfile`, in `unzip`,
and in macOS `ditto`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/features/drive_relay/test_zip_stream.py
import io
import zipfile

import pytest

from railway.features.drive_relay.zip_stream import TransferCapExceeded, stream_zip

CAP = 10 * 1024 * 1024


def read_back(chunks):
    return zipfile.ZipFile(io.BytesIO(b"".join(chunks)))


def test_produces_a_readable_archive():
    archive = read_back(stream_zip([("a.txt", [b"hello ", b"world"])], max_bytes=CAP))

    assert archive.testzip() is None
    assert archive.read("a.txt") == b"hello world"


def test_preserves_folder_structure_and_order():
    entries = [("Intro.pdf", [b"1"]), ("Day 2/Lab.pdf", [b"2"]), ("Day 2/Sol/A.pdf", [b"3"])]

    archive = read_back(stream_zip(entries, max_bytes=CAP))

    assert archive.namelist() == ["Intro.pdf", "Day 2/Lab.pdf", "Day 2/Sol/A.pdf"]


def test_preserves_unicode_names():
    archive = read_back(stream_zip([("Note — ünïcode.txt", [b"x"])], max_bytes=CAP))

    assert archive.read("Note — ünïcode.txt") == b"x"


def test_stores_without_compression():
    archive = read_back(stream_zip([("a.bin", [b"x" * 5000])], max_bytes=CAP))

    assert archive.infolist()[0].compress_type == zipfile.ZIP_STORED


def test_memory_stays_flat_for_large_files():
    """A 4 MB file must never be buffered whole — yields stay chunk-sized."""
    chunks = list(stream_zip([("big.bin", (b"x" * 65536 for _ in range(64)))], max_bytes=CAP))

    assert max(len(c) for c in chunks) < 200 * 1024
    assert read_back(chunks).read("big.bin") == b"x" * (65536 * 64)


def test_empty_archive_is_still_valid():
    archive = read_back(stream_zip([], max_bytes=CAP))

    assert archive.namelist() == []


def test_raises_once_payload_exceeds_the_cap():
    entries = [("big.bin", (b"x" * 1024 for _ in range(200)))]

    with pytest.raises(TransferCapExceeded):
        list(stream_zip(entries, max_bytes=100 * 1024))


def test_cap_counts_across_entries_not_per_entry():
    entries = [("a.bin", [b"x" * 60_000]), ("b.bin", [b"y" * 60_000])]

    with pytest.raises(TransferCapExceeded):
        list(stream_zip(entries, max_bytes=100_000))


def test_stays_under_the_cap_without_raising():
    chunks = list(stream_zip([("a.bin", [b"x" * 90_000])], max_bytes=100_000))

    assert read_back(chunks).read("a.bin") == b"x" * 90_000
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_zip_stream.py -v`
Expected: FAIL — `ModuleNotFoundError: ... zip_stream`

- [ ] **Step 3: Write the implementation**

```python
# railway/features/drive_relay/zip_stream.py
"""Build a zip archive as a byte stream, with nothing buffered and nothing on disk.

stdlib `zipfile` can write into an unseekable stream: it detects the missing
`seek` and emits data descriptors on its own. So we hand it a sink that just
accumulates writes, and drain that sink after every chunk we push in. Zip-format
correctness (data descriptors, zip64, unicode flags) stays inside the stdlib
instead of in hand-rolled header code.

STORED, not DEFLATE: course materials are already PDF/PPTX/zip, so compressing
them burns CPU on a shared box for no size win.
"""
from __future__ import annotations

import io
import zipfile
from typing import Iterable, Iterator, Tuple


class TransferCapExceeded(RuntimeError):
    """The archive payload grew past the caller's byte cap."""


class _Sink(io.RawIOBase):
    """An unseekable write target that hands its bytes back on demand."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def write(self, data) -> int:  # type: ignore[override]
        self._buffer += data
        return len(data)

    def writable(self) -> bool:
        return True

    def drain(self) -> bytes:
        data = bytes(self._buffer)
        self._buffer.clear()
        return data


def stream_zip(
    entries: Iterable[Tuple[str, Iterable[bytes]]],
    max_bytes: int,
) -> Iterator[bytes]:
    """Yield the bytes of a zip holding ``entries`` as (archive_path, chunks).

    Raises TransferCapExceeded as soon as the payload passes ``max_bytes``. The
    caller is mid-response by then, so this cuts the download off rather than
    turning into a status code — the pre-check in the router is what produces a
    clean refusal.
    """
    sink = _Sink()
    written = 0

    with zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED) as archive:
        for archive_path, chunks in entries:
            with archive.open(archive_path, "w", force_zip64=True) as target:
                for chunk in chunks:
                    written += len(chunk)
                    if written > max_bytes:
                        raise TransferCapExceeded(
                            f"Transfer exceeded {max_bytes} bytes"
                        )
                    target.write(chunk)
                    payload = sink.drain()
                    if payload:
                        yield payload
            payload = sink.drain()
            if payload:
                yield payload

    payload = sink.drain()
    if payload:
        yield payload
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_zip_stream.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add railway/features/drive_relay/zip_stream.py tests/features/drive_relay/test_zip_stream.py
git commit -m "feat(drive-relay): stream a zip with constant memory and no disk"
```

---

### Task 7: Preview endpoint and app wiring

**Files:**
- Create: `railway/features/drive_relay/router.py`
- Modify: `railway/app.py` (imports near line 15-25; registration in the root-level block, before `session_host`)
- Modify: `openapi.json` (regenerate)
- Test: `tests/features/drive_relay/test_router_preview.py`

**Interfaces:**
- Consumes: `parse_drive_url`, `InvalidDriveLink`, `drive_client`, `ownership`, `tree`.
- Produces:
  - `router: APIRouter` — carries `/api/drive/preview` and (Task 8) `/api/drive/zip`
  - `page_router: APIRouter` — carries `/drive` (Task 9)
  - `class DrivePreviewResponse(BaseModel): name: str; file_count: int; total_bytes: int; has_unsized_files: bool`
  - `resolve_plan(url: str) -> Tuple[DriveFile, TransferPlan]` — raises `HTTPException`
  - `MAX_TRANSFER_BYTES: int`

Copy strings (use verbatim; also used in Task 8):

```python
BAD_LINK = "That doesn't look like a Google Drive link"
NOT_AVAILABLE = "This folder is not shared publicly, or the link is wrong"
DRIVE_DOWN = "Google Drive is not responding right now — please try again"
TOO_LARGE = "This folder is larger than 500 MB — ask Victor to split it or send it another way"
```

A folder owned by someone else answers 404, not 403 — same status AND same message as
a folder that does not exist. Matching only the message still leaves the status code as
an oracle: 403 would fire solely for folders that are real, public and owned by someone
else, sorting folder ids into "Victor's" and "not Victor's" without reading the body.

Blocking `urllib` calls must not run on the event loop: wrap them in
`starlette.concurrency.run_in_threadpool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/features/drive_relay/test_router_preview.py
import pytest
from fastapi.testclient import TestClient

from railway.app import app
from railway.features.drive_relay import router as relay
from railway.features.drive_relay.drive_client import FOLDER_MIME, DriveError, DriveFile, DriveOwner

FOLDER_ID = "1A2b3C4d5E6f7G8h9I0jKlMnOpQrStUv"
FOLDER_URL = f"https://drive.google.com/drive/folders/{FOLDER_ID}"

client = TestClient(app)


def owned_folder():
    return DriveFile(
        id=FOLDER_ID, name="Workshop Materials", mime_type=FOLDER_MIME, size=None,
        owners=(DriveOwner(email="victorrentea@gmail.com", permission_id="1", display_name="V"),),
        shortcut_target_id=None,
    )


def pdf(id, name, size):
    return DriveFile(id=id, name=name, mime_type="application/pdf", size=size, owners=(),
                     shortcut_target_id=None)


@pytest.fixture(autouse=True)
def owner_env(monkeypatch):
    monkeypatch.setenv("DRIVE_OWNER_EMAILS", "victorrentea@gmail.com")
    monkeypatch.setenv("GOOGLE_DRIVE_API_KEY", "test-key")
    monkeypatch.setenv("GATEWAY_RATE_LIMIT_DISABLED", "1")


@pytest.fixture
def drive(monkeypatch):
    state = {"root": owned_folder(), "children": {}}
    monkeypatch.setattr(relay.drive_client, "get_metadata", lambda fid: state["root"])
    monkeypatch.setattr(relay.tree.drive_client, "get_metadata", lambda fid: state["root"])
    monkeypatch.setattr(relay.tree.drive_client, "list_children",
                        lambda fid: state["children"].get(fid, []))
    return state


def test_preview_reports_the_folder_contents(drive):
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 1000), pdf("b", "Lab.pdf", 2000)]

    response = client.get("/api/drive/preview", params={"url": FOLDER_URL})

    assert response.status_code == 200
    assert response.json() == {
        "name": "Workshop Materials",
        "file_count": 2,
        "total_bytes": 3000,
        "has_unsized_files": False,
    }


def test_preview_flags_unsized_native_files(drive):
    drive["children"][FOLDER_ID] = [
        DriveFile(id="d", name="Agenda", mime_type="application/vnd.google-apps.document",
                  size=None, owners=(), shortcut_target_id=None)
    ]

    body = client.get("/api/drive/preview", params={"url": FOLDER_URL}).json()

    assert body["has_unsized_files"] is True
    assert body["total_bytes"] == 0


def test_preview_rejects_a_non_drive_link():
    response = client.get("/api/drive/preview", params={"url": "https://example.com/x"})

    assert response.status_code == 400
    assert response.json()["detail"] == relay.BAD_LINK


def test_preview_rejects_a_folder_owned_by_someone_else(drive, monkeypatch):
    stranger = DriveFile(id=FOLDER_ID, name="Someone Else", mime_type=FOLDER_MIME, size=None,
                         owners=(DriveOwner(email="x@y.com", permission_id="9", display_name=""),),
                         shortcut_target_id=None)
    monkeypatch.setattr(relay.drive_client, "get_metadata", lambda fid: stranger)

    response = client.get("/api/drive/preview", params={"url": FOLDER_URL})

    assert response.status_code == 404
    assert response.json()["detail"] == relay.NOT_AVAILABLE


def test_missing_and_not_owned_are_indistinguishable(drive, monkeypatch):
    """The message must not reveal which folders belong to the trainer."""
    def missing(fid):
        raise DriveError(404, "gone")

    monkeypatch.setattr(relay.drive_client, "get_metadata", missing)
    not_found = client.get("/api/drive/preview", params={"url": FOLDER_URL})

    assert not_found.status_code == 404
    assert not_found.json()["detail"] == relay.NOT_AVAILABLE


def test_preview_maps_drive_outage_to_502(drive, monkeypatch):
    def unreachable(fid):
        raise DriveError(502, "boom")

    monkeypatch.setattr(relay.drive_client, "get_metadata", unreachable)

    response = client.get("/api/drive/preview", params={"url": FOLDER_URL})

    assert response.status_code == 502
    assert response.json()["detail"] == relay.DRIVE_DOWN


def test_preview_refuses_a_folder_over_the_cap(drive):
    drive["children"][FOLDER_ID] = [pdf("a", "Huge.bin", relay.MAX_TRANSFER_BYTES + 1)]

    response = client.get("/api/drive/preview", params={"url": FOLDER_URL})

    assert response.status_code == 413
    assert response.json()["detail"] == relay.TOO_LARGE


def test_preview_works_with_no_active_session(drive):
    """The whole point: no session, no daemon, still answers."""
    from railway.shared.state import state
    state.reset()
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 10)]

    assert client.get("/api/drive/preview", params={"url": FOLDER_URL}).status_code == 200


def test_drive_routes_are_not_shadowed_by_the_session_catch_all():
    """Regression guard: /{session_id} must not swallow /api/drive/*."""
    routes = [r.path for r in app.routes]
    assert "/api/drive/preview" in routes
    assert routes.index("/api/drive/preview") < routes.index("/{session_id}/{tab}")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_router_preview.py -v`
Expected: FAIL — `ModuleNotFoundError: ... drive_relay.router`

- [ ] **Step 3: Write the router**

```python
# railway/features/drive_relay/router.py
"""HTTP surface of the Drive relay.

Session-independent and daemon-independent by construction: nothing here imports
session state or the daemon WebSocket, so it answers while the trainer's laptop
is closed.
"""
from __future__ import annotations

import logging
from typing import Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from railway.features.drive_relay import drive_client, ownership, tree
from railway.features.drive_relay.drive_client import DriveError, DriveFile
from railway.features.drive_relay.link_parser import InvalidDriveLink, parse_drive_url
from railway.features.drive_relay.tree import TransferPlan
from railway.shared.rate_limit import rate_limit_probe

logger = logging.getLogger(__name__)

router = APIRouter()
page_router = APIRouter()

MAX_TRANSFER_BYTES = 500 * 1024 * 1024

BAD_LINK = "That doesn't look like a Google Drive link"
NOT_AVAILABLE = "This folder is not shared publicly, or the link is wrong"
DRIVE_DOWN = "Google Drive is not responding right now — please try again"
TOO_LARGE = (
    "This folder is larger than 500 MB — ask Victor to split it or send it another way"
)


class DrivePreviewResponse(BaseModel):
    name: str
    file_count: int
    total_bytes: int
    has_unsized_files: bool


def _load_root(url: str) -> DriveFile:
    try:
        file_id = parse_drive_url(url)
    except InvalidDriveLink:
        raise HTTPException(status_code=400, detail=BAD_LINK) from None

    try:
        root = drive_client.get_metadata(file_id)
    except DriveError as exc:
        if exc.status in (401, 403, 404):
            logger.info("[drive-relay] refused %s: Drive returned %s", file_id, exc.status)
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None
        logger.warning("[drive-relay] Drive error for %s: %s", file_id, exc)
        raise HTTPException(status_code=502, detail=DRIVE_DOWN) from None

    emails, permission_ids = ownership.configured_identity()
    if not ownership.is_owned_by_host(root, emails=emails, permission_ids=permission_ids):
        logger.warning("[drive-relay] refused %s: not owned by the configured trainer", file_id)
        raise HTTPException(status_code=404, detail=NOT_AVAILABLE)

    return root


def _resolve_plan_sync(url: str) -> Tuple[DriveFile, TransferPlan]:
    root = _load_root(url)
    try:
        plan = tree.build_plan(root)
    except DriveError as exc:
        logger.warning("[drive-relay] listing failed for %s: %s", root.id, exc)
        raise HTTPException(status_code=502, detail=DRIVE_DOWN) from None

    if plan.known_bytes > MAX_TRANSFER_BYTES:
        raise HTTPException(status_code=413, detail=TOO_LARGE)
    return root, plan


async def resolve_plan(url: str) -> Tuple[DriveFile, TransferPlan]:
    """Validate the link and plan the transfer, off the event loop.

    Drive calls go through blocking urllib (the same stdlib-only approach as
    railway/features/slides/cache.py), so they must not run on the loop.
    """
    return await run_in_threadpool(_resolve_plan_sync, url)


@router.get(
    "/api/drive/preview",
    response_model=DrivePreviewResponse,
    operation_id="get_drive_preview",
    dependencies=[Depends(rate_limit_probe)],
)
async def get_drive_preview(url: str) -> DrivePreviewResponse:
    """Validate a pasted Drive link and describe what a download would contain."""
    _, plan = await resolve_plan(url)
    return DrivePreviewResponse(
        name=plan.root_name,
        file_count=len(plan.entries),
        total_bytes=plan.known_bytes,
        has_unsized_files=plan.has_unsized_files,
    )
```

- [ ] **Step 4: Wire it into the app**

In `railway/app.py`, add to the imports (alphabetical position, after
`railway.features.bridge.router`):

```python
from railway.features.drive_relay.router import page_router as drive_page_router
from railway.features.drive_relay.router import router as drive_router
```

and register in the root-level block, immediately after
`app.include_router(internal_router)`:

```python
# Google Drive relay: participants behind Drive-blocking networks paste a link and
# get a zip. Root-level and session-free on purpose — it must answer with the daemon
# offline. Registered here, before the /{session_id} catch-all at the bottom.
app.include_router(drive_router)
app.include_router(drive_page_router)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_router_preview.py -v`
Expected: PASS (9 tests)

- [ ] **Step 6: Regenerate the OpenAPI contract**

```bash
uv run --extra dev python3 -c "from railway.app import app; import json; print(json.dumps(app.openapi(), indent=2))" > openapi.json
uv run --extra dev pytest tests/openapi/test_contract.py -v
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add railway/features/drive_relay/router.py railway/app.py openapi.json \
        tests/features/drive_relay/test_router_preview.py
git commit -m "feat(drive-relay): preview endpoint validating link, owner and size"
```

---

### Task 8: Zip download endpoint

**Files:**
- Modify: `railway/features/drive_relay/router.py`
- Modify: `railway/shared/rate_limit.py` (add the strict bucket)
- Modify: `openapi.json` (regenerate)
- Test: `tests/features/drive_relay/test_router_zip.py`

**Interfaces:**
- Consumes: `resolve_plan`, `MAX_TRANSFER_BYTES`, `zip_stream.stream_zip`, `drive_client.open_download`.
- Produces:
  - `GET /api/drive/zip?url=...` → `StreamingResponse` (`application/zip`)
  - In `railway/shared/rate_limit.py`: `drive_zip_limiter: TokenBucketLimiter`,
    `async def rate_limit_drive_zip(request: Request) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/features/drive_relay/test_router_zip.py
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from railway.app import app
from railway.features.drive_relay import router as relay
from railway.features.drive_relay.drive_client import FOLDER_MIME, DriveFile, DriveOwner
from railway.shared import rate_limit

FOLDER_ID = "1A2b3C4d5E6f7G8h9I0jKlMnOpQrStUv"
FOLDER_URL = f"https://drive.google.com/drive/folders/{FOLDER_ID}"

client = TestClient(app)


def owned_folder(name="Workshop Materials"):
    return DriveFile(
        id=FOLDER_ID, name=name, mime_type=FOLDER_MIME, size=None,
        owners=(DriveOwner(email="victorrentea@gmail.com", permission_id="1", display_name="V"),),
        shortcut_target_id=None,
    )


def pdf(id, name, size):
    return DriveFile(id=id, name=name, mime_type="application/pdf", size=size, owners=(),
                     shortcut_target_id=None)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("DRIVE_OWNER_EMAILS", "victorrentea@gmail.com")
    monkeypatch.setenv("GOOGLE_DRIVE_API_KEY", "test-key")
    monkeypatch.setenv("GATEWAY_RATE_LIMIT_DISABLED", "1")
    rate_limit.drive_zip_limiter.reset()


@pytest.fixture
def drive(monkeypatch):
    state = {"root": owned_folder(), "children": {}, "bodies": {}}
    monkeypatch.setattr(relay.drive_client, "get_metadata", lambda fid: state["root"])
    monkeypatch.setattr(relay.tree.drive_client, "get_metadata", lambda fid: state["root"])
    monkeypatch.setattr(relay.tree.drive_client, "list_children",
                        lambda fid: state["children"].get(fid, []))
    monkeypatch.setattr(relay.drive_client, "open_download",
                        lambda file: iter([state["bodies"].get(file.id, b"")]))
    return state


def test_zip_contains_every_file(drive):
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 5), pdf("b", "Lab.pdf", 3)]
    drive["bodies"] = {"a": b"INTRO", "b": b"LAB"}

    response = client.get("/api/drive/zip", params={"url": FOLDER_URL})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert archive.namelist() == ["Intro.pdf", "Lab.pdf"]
    assert archive.read("Intro.pdf") == b"INTRO"


def test_zip_is_named_after_the_folder(drive):
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 5)]
    drive["bodies"] = {"a": b"INTRO"}

    disposition = client.get("/api/drive/zip", params={"url": FOLDER_URL}).headers[
        "content-disposition"
    ]

    assert "Workshop Materials.zip" in disposition


def test_unicode_folder_names_survive_the_header(drive, monkeypatch):
    monkeypatch.setattr(relay.drive_client, "get_metadata", lambda fid: owned_folder("Curs Programare"))
    monkeypatch.setattr(relay.tree.drive_client, "get_metadata", lambda fid: owned_folder("Curs Programare"))
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 5)]
    drive["bodies"] = {"a": b"INTRO"}

    disposition = client.get("/api/drive/zip", params={"url": FOLDER_URL}).headers[
        "content-disposition"
    ]

    assert "filename*=UTF-8''" in disposition


def test_never_redirects_the_browser_to_google(drive):
    """The whole feature exists because participants cannot reach Google."""
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 5)]
    drive["bodies"] = {"a": b"INTRO"}

    response = client.get("/api/drive/zip", params={"url": FOLDER_URL}, follow_redirects=False)

    assert response.status_code == 200
    assert "location" not in {k.lower() for k in response.headers}


def test_zip_rejects_a_bad_link():
    response = client.get("/api/drive/zip", params={"url": "https://example.com/x"})

    assert response.status_code == 400
    assert response.json()["detail"] == relay.BAD_LINK


def test_zip_refuses_a_folder_over_the_cap(drive):
    drive["children"][FOLDER_ID] = [pdf("a", "Huge.bin", relay.MAX_TRANSFER_BYTES + 1)]

    response = client.get("/api/drive/zip", params={"url": FOLDER_URL})

    assert response.status_code == 413
    assert response.json()["detail"] == relay.TOO_LARGE


def test_a_single_file_link_streams_that_file_not_a_zip(drive, monkeypatch):
    single = pdf("f1", "Deck.pdf", 4)
    monkeypatch.setattr(relay.drive_client, "get_metadata", lambda fid: DriveFile(
        id="f1", name="Deck.pdf", mime_type="application/pdf", size=4,
        owners=(DriveOwner(email="victorrentea@gmail.com", permission_id="1", display_name="V"),),
        shortcut_target_id=None))
    monkeypatch.setattr(relay.drive_client, "open_download", lambda file: iter([b"PDF!"]))

    response = client.get(
        "/api/drive/zip",
        params={"url": f"https://drive.google.com/file/d/{FOLDER_ID}/view"},
    )

    assert response.status_code == 200
    assert response.content == b"PDF!"
    assert response.headers["content-type"] == "application/pdf"
    assert "Deck.pdf" in response.headers["content-disposition"]
    assert single.name == "Deck.pdf"


def test_rate_limiter_allows_three_downloads_then_throttles(monkeypatch, drive):
    monkeypatch.delenv("GATEWAY_RATE_LIMIT_DISABLED", raising=False)
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 5)]
    drive["bodies"] = {"a": b"INTRO"}
    headers = {"X-Forwarded-For": "203.0.113.7"}

    codes = [
        client.get("/api/drive/zip", params={"url": FOLDER_URL}, headers=headers).status_code
        for _ in range(4)
    ]

    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429


def test_preview_is_not_throttled_by_the_zip_bucket(monkeypatch, drive):
    monkeypatch.delenv("GATEWAY_RATE_LIMIT_DISABLED", raising=False)
    drive["children"][FOLDER_ID] = [pdf("a", "Intro.pdf", 5)]
    drive["bodies"] = {"a": b"INTRO"}
    headers = {"X-Forwarded-For": "203.0.113.8"}

    for _ in range(4):
        client.get("/api/drive/zip", params={"url": FOLDER_URL}, headers=headers)

    assert client.get("/api/drive/preview", params={"url": FOLDER_URL},
                      headers=headers).status_code == 200
```

Note: `TestClient` presents a loopback peer, which `rate_limit._is_exempt` normally
exempts. The two throttling tests therefore also need the exemption disabled; add
`monkeypatch.setattr(rate_limit, "_EXEMPT_PEERS", frozenset())` to both, right after
the `delenv` line.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_router_zip.py -v`
Expected: FAIL — `AttributeError: module 'railway.shared.rate_limit' has no attribute 'drive_zip_limiter'`

- [ ] **Step 3: Add the strict rate-limit bucket**

Append to `railway/shared/rate_limit.py`:

```python
# Drive-relay downloads are the one endpoint where a single request can cost
# hundreds of megabytes of egress, so it gets its own far stricter budget than
# the probe endpoints: three downloads, then one more every five minutes.
_DRIVE_ZIP_CAPACITY = int(os.environ.get("DRIVE_ZIP_RATE_CAPACITY", "3"))
_DRIVE_ZIP_REFILL_PER_SEC = float(
    os.environ.get("DRIVE_ZIP_RATE_REFILL_PER_SEC", str(1.0 / 300.0))
)

drive_zip_limiter = TokenBucketLimiter(_DRIVE_ZIP_CAPACITY, _DRIVE_ZIP_REFILL_PER_SEC)


async def rate_limit_drive_zip(request: Request) -> None:
    """FastAPI dependency: throttle Drive-relay zip downloads per client IP."""
    if os.environ.get("GATEWAY_RATE_LIMIT_DISABLED") == "1":
        return
    if _is_exempt(request):
        return
    if not drive_zip_limiter.allow(_client_key(request)):
        raise HTTPException(
            status_code=429,
            detail="Too many downloads — please wait a few minutes and try again",
            headers={"Retry-After": "300"},
        )
```

- [ ] **Step 4: Add the zip endpoint**

Add to `railway/features/drive_relay/router.py` — imports first:

```python
import urllib.parse
from typing import Iterator

from fastapi.responses import StreamingResponse

from railway.features.drive_relay.zip_stream import TransferCapExceeded, stream_zip
from railway.shared.rate_limit import rate_limit_drive_zip
```

then:

```python
def _content_disposition(filename: str) -> str:
    """RFC 5987 disposition so unicode course names survive the header."""
    ascii_fallback = filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    quoted = urllib.parse.quote(filename, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quoted}"


def _archive_chunks(plan: TransferPlan) -> Iterator[bytes]:
    """Yield the archive, downloading each file only as the client consumes it."""
    entries = ((entry.archive_path, drive_client.open_download(entry.file))
               for entry in plan.entries)
    try:
        for chunk in stream_zip(entries, max_bytes=MAX_TRANSFER_BYTES):
            yield chunk
    except TransferCapExceeded:
        # Mid-response: the status line is long gone, so the download is simply
        # cut off. Reaching here means the pre-check under-counted, which happens
        # when the folder is full of Google-native files (they report no size).
        logger.warning("[drive-relay] transfer cap hit mid-stream for %s", plan.root_name)
        return
    except DriveError as exc:
        logger.warning("[drive-relay] download failed mid-stream for %s: %s", plan.root_name, exc)
        return


@router.get(
    "/api/drive/zip",
    operation_id="get_drive_zip",
    response_class=StreamingResponse,
    dependencies=[Depends(rate_limit_drive_zip)],
)
async def get_drive_zip(url: str) -> StreamingResponse:
    """Stream the pasted Drive folder as a zip. A single file streams as itself.

    Every byte is relayed through this server — we follow Drive's own redirects
    inside drive_client and never hand one to the browser, because the
    participants this exists for cannot reach Google at all.
    """
    root, plan = await resolve_plan(url)

    if not drive_client.is_folder(root):
        entry = plan.entries[0]
        logger.info("[drive-relay] ↓ single file %s (%s bytes)", entry.archive_path,
                    entry.file.size)
        return StreamingResponse(
            drive_client.open_download(entry.file),
            media_type=entry.file.mime_type or "application/octet-stream",
            headers={
                "Content-Disposition": _content_disposition(entry.archive_path),
                "Cache-Control": "no-store",
            },
        )

    logger.info("[drive-relay] ↓ zip '%s' (%d files, %d known bytes)",
                plan.root_name, len(plan.entries), plan.known_bytes)
    return StreamingResponse(
        _archive_chunks(plan),
        media_type="application/zip",
        headers={
            "Content-Disposition": _content_disposition(f"{plan.root_name}.zip"),
            "Cache-Control": "no-store",
        },
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/features/drive_relay/ -v`
Expected: PASS (all files)

- [ ] **Step 6: Regenerate the OpenAPI contract**

```bash
uv run --extra dev python3 -c "from railway.app import app; import json; print(json.dumps(app.openapi(), indent=2))" > openapi.json
uv run --extra dev pytest tests/openapi/test_contract.py -v
```
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add railway/features/drive_relay/router.py railway/shared/rate_limit.py openapi.json \
        tests/features/drive_relay/test_router_zip.py
git commit -m "feat(drive-relay): stream the folder as a zip, rate-limited per IP"
```

---

### Task 9: The `/drive` page

**Files:**
- Create: `static/drive.html`
- Modify: `railway/features/drive_relay/router.py` (add the page route to `page_router`)
- Modify: `openapi.json` (regenerate)
- Test: `tests/features/drive_relay/test_page.py`

**Interfaces:**
- Consumes: `page_router` from Task 7, `_serve_html_with_otel` from `railway.features.pages.router`.
- Produces: `GET /drive` → the HTML page.

All copy in English. Visual polish is a deliberate follow-up — this task delivers a
working, correct screen, not a designed one.

- [ ] **Step 1: Write the failing tests**

```python
# tests/features/drive_relay/test_page.py
from fastapi.testclient import TestClient

from railway.app import app

client = TestClient(app)


def test_drive_page_is_served():
    response = client.get("/drive")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_page_carries_the_shared_csp():
    assert "default-src 'self'" in client.get("/drive").headers["content-security-policy"]


def test_page_never_points_the_browser_at_google():
    """Participants reaching this page cannot load anything from Google."""
    body = client.get("/drive").text

    assert "drive.google.com" not in body
    assert "googleapis.com" not in body
    assert "gstatic.com" not in body


def test_page_has_the_paste_field_and_button():
    body = client.get("/drive").text

    assert 'id="drive-url"' in body
    assert 'id="check-btn"' in body


def test_page_is_reachable_with_no_active_session():
    from railway.shared.state import state
    state.reset()

    assert client.get("/drive").status_code == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_page.py -v`
Expected: FAIL — 404 on `/drive`

- [ ] **Step 3: Write the page**

```html
<!-- static/drive.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Download course materials</title>
  <link rel="stylesheet" href="/static/common.css">
  <style>
    .relay { max-width: 640px; margin: 4rem auto; padding: 0 1rem; }
    .relay__row { display: flex; gap: .5rem; margin: 1.5rem 0; }
    .relay__row input { flex: 1; padding: .6rem; font-size: 1rem; }
    .relay__panel { padding: 1rem; border: 1px solid currentColor; border-radius: 6px; }
    .relay__error { color: #b00020; }
    [hidden] { display: none !important; }
  </style>
</head>
<body>
  <main class="relay">
    <h1>Download course materials</h1>
    <p>
      Paste the Google Drive link you received by email. The download is served
      from this server, so it works on networks that block Google Drive.
    </p>

    <div class="relay__row">
      <input id="drive-url" type="url" placeholder="Paste your Google Drive link"
             autocomplete="off" spellcheck="false">
      <button id="check-btn" type="button" disabled>Check link</button>
    </div>

    <p id="status" hidden></p>

    <div id="preview" class="relay__panel" hidden>
      <p><strong id="preview-name"></strong></p>
      <p id="preview-detail"></p>
      <button id="download-btn" type="button">Download zip</button>
    </div>

    <p id="error" class="relay__error" hidden></p>
  </main>

  <script>
    const urlInput = document.getElementById('drive-url');
    const checkBtn = document.getElementById('check-btn');
    const downloadBtn = document.getElementById('download-btn');
    const statusEl = document.getElementById('status');
    const previewEl = document.getElementById('preview');
    const previewName = document.getElementById('preview-name');
    const previewDetail = document.getElementById('preview-detail');
    const errorEl = document.getElementById('error');

    let currentUrl = '';

    // Project convention: a button whose input is empty stays disabled.
    urlInput.addEventListener('input', () => {
      checkBtn.disabled = urlInput.value.trim() === '';
    });

    function show(el, text) {
      if (text !== undefined) el.textContent = text;
      el.hidden = false;
    }

    function hideAll() {
      previewEl.hidden = true;
      errorEl.hidden = true;
      statusEl.hidden = true;
    }

    function formatSize(bytes) {
      if (bytes < 1024 * 1024) return Math.max(1, Math.round(bytes / 1024)) + ' KB';
      return (bytes / 1024 / 1024).toFixed(1) + ' MB';
    }

    async function check() {
      const value = urlInput.value.trim();
      if (!value) return;
      hideAll();
      checkBtn.disabled = true;
      show(statusEl, 'Checking the link…');

      try {
        const response = await fetch('/api/drive/preview?url=' + encodeURIComponent(value));
        const body = await response.json();
        statusEl.hidden = true;

        if (!response.ok) {
          show(errorEl, body.detail || 'Something went wrong — please try again');
          return;
        }

        currentUrl = value;
        previewName.textContent = body.name;
        const size = body.has_unsized_files
          ? 'at least ' + formatSize(body.total_bytes)
          : formatSize(body.total_bytes);
        previewDetail.textContent = body.file_count + ' file'
          + (body.file_count === 1 ? '' : 's') + ' · ' + size;
        show(previewEl);
      } catch (err) {
        statusEl.hidden = true;
        show(errorEl, 'Could not reach the server — please try again');
      } finally {
        checkBtn.disabled = urlInput.value.trim() === '';
      }
    }

    checkBtn.addEventListener('click', check);
    urlInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') check(); });

    downloadBtn.addEventListener('click', () => {
      // Plain navigation: the browser's own download UI reports progress.
      window.location.href = '/api/drive/zip?url=' + encodeURIComponent(currentUrl);
    });
  </script>
</body>
</html>
```

- [ ] **Step 4: Add the page route**

In `railway/features/drive_relay/router.py`:

```python
from fastapi.responses import HTMLResponse

from railway.features.pages.router import _serve_html_with_otel


@page_router.get("/drive", response_class=HTMLResponse, include_in_schema=False)
async def drive_relay_page():
    """The paste-a-link page. Public and session-free, like the relay itself."""
    return _serve_html_with_otel("static/drive.html")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --extra dev pytest tests/features/drive_relay/test_page.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Confirm the page renders**

Run the backend locally and open `http://localhost:8000/drive`, paste a junk link, and
confirm the error message appears rather than a blank screen. Capture a screenshot for
the task report — this project requires visual proof for visual changes.

- [ ] **Step 7: Regenerate the OpenAPI contract and commit**

```bash
uv run --extra dev python3 -c "from railway.app import app; import json; print(json.dumps(app.openapi(), indent=2))" > openapi.json
git add static/drive.html railway/features/drive_relay/router.py openapi.json \
        tests/features/drive_relay/test_page.py
git commit -m "feat(drive-relay): /drive page for pasting a link and downloading the zip"
```

---

### Task 10: Hermetic Docker test

**Files:**
- Modify: `tests/docker/mock_drive_server.py` (add Drive API v3 routes)
- Create: `tests/docker/test_drive_relay.py`

**Interfaces:**
- Consumes: the whole feature over HTTP.
- Produces: nothing other tasks depend on.

The critical scenario is the one no unit test can prove: **the relay answers with the
daemon stopped.**

- [ ] **Step 1: Extend the mock Drive server**

Add to `MockDriveHandler.do_GET` in `tests/docker/mock_drive_server.py`, before the
existing export-URL handling. Fixtures are described by a module-level dict so tests
can assert against known content:

```python
# Drive API v3 surface for the drive-relay tests. Shape mirrors the real API
# closely enough that railway/features/drive_relay/drive_client.py cannot tell.
DRIVE_FIXTURES = {
    "rootfolder0000000000": {
        "id": "rootfolder0000000000", "name": "Hermetic Materials",
        "mimeType": "application/vnd.google-apps.folder",
        "owners": [{"emailAddress": "victorrentea@gmail.com",
                    "permissionId": "111", "displayName": "Victor"}],
        "children": ["intro000000000000000", "subfolder00000000000"],
    },
    "subfolder00000000000": {
        "id": "subfolder00000000000", "name": "Day 2",
        "mimeType": "application/vnd.google-apps.folder",
        "owners": [{"emailAddress": "victorrentea@gmail.com",
                    "permissionId": "111", "displayName": "Victor"}],
        "children": ["lab00000000000000000"],
    },
    "intro000000000000000": {
        "id": "intro000000000000000", "name": "Intro.pdf",
        "mimeType": "application/pdf", "size": "5", "body": b"INTRO",
        "owners": [{"emailAddress": "victorrentea@gmail.com",
                    "permissionId": "111", "displayName": "Victor"}],
    },
    "lab00000000000000000": {
        "id": "lab00000000000000000", "name": "Lab.pdf",
        "mimeType": "application/pdf", "size": "3", "body": b"LAB",
        "owners": [{"emailAddress": "victorrentea@gmail.com",
                    "permissionId": "111", "displayName": "Victor"}],
    },
    "agenda00000000000000": {
        "id": "agenda00000000000000", "name": "Agenda",
        "mimeType": "application/vnd.google-apps.document", "body": b"%PDF-agenda",
        "owners": [{"emailAddress": "victorrentea@gmail.com",
                    "permissionId": "111", "displayName": "Victor"}],
    },
    "stranger000000000000": {
        "id": "stranger000000000000", "name": "Someone Else's Folder",
        "mimeType": "application/vnd.google-apps.folder",
        "owners": [{"emailAddress": "stranger@example.com",
                    "permissionId": "999", "displayName": "Stranger"}],
        "children": [],
    },
}

_METADATA_KEYS = ("id", "name", "mimeType", "size", "owners")


def _metadata(entry):
    return {k: entry[k] for k in _METADATA_KEYS if k in entry}
```

and the routing inside `do_GET`:

```python
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        # GET /drive/v3/files?q='<id>' in parents and trashed = false
        if parsed.path == "/drive/v3/files":
            q = (query.get("q") or [""])[0]
            match = re.search(r"'([^']+)' in parents", q)
            parent = DRIVE_FIXTURES.get(match.group(1)) if match else None
            files = [_metadata(DRIVE_FIXTURES[c]) for c in (parent or {}).get("children", [])]
            self._send_json({"files": files})
            return

        # GET /drive/v3/files/{id}[?alt=media]  and  /drive/v3/files/{id}/export
        api_match = re.match(r"^/drive/v3/files/([^/]+)(/export)?$", parsed.path)
        if api_match:
            entry = DRIVE_FIXTURES.get(api_match.group(1))
            if entry is None:
                self.send_error(404)
                return
            if api_match.group(2) or query.get("alt") == ["media"]:
                self._send_bytes(entry.get("body", b""), entry.get("mimeType", "application/octet-stream"))
            else:
                self._send_json(_metadata(entry))
            return
```

plus the two helpers on the handler:

```python
    def _send_json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
```

Add `import re` and `import urllib.parse` at the top of the module.

- [ ] **Step 2: Write the failing hermetic test**

```python
# tests/docker/test_drive_relay.py
"""Hermetic tests for the Drive relay: real backend, mock Drive, no daemon needed."""
import io
import zipfile

import pytest
import requests

ROOT_ID = "rootfolder0000000000"
STRANGER_ID = "stranger000000000000"


def drive_url(file_id):
    return f"https://drive.google.com/drive/folders/{file_id}"


def test_preview_describes_the_folder():
    response = requests.get(f"{BASE}/api/drive/preview",
                            params={"url": drive_url(ROOT_ID)}, timeout=30)

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Hermetic Materials"
    assert body["file_count"] == 2
    assert body["total_bytes"] == 8


def test_zip_contains_the_whole_tree():
    response = requests.get(f"{BASE}/api/drive/zip",
                            params={"url": drive_url(ROOT_ID)}, timeout=60)

    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert archive.namelist() == ["Intro.pdf", "Day 2/Lab.pdf"]
    assert archive.read("Intro.pdf") == b"INTRO"
    assert archive.read("Day 2/Lab.pdf") == b"LAB"


def test_a_strangers_folder_is_refused():
    response = requests.get(f"{BASE}/api/drive/zip",
                            params={"url": drive_url(STRANGER_ID)}, timeout=30)

    assert response.status_code == 404


def test_the_browser_is_never_redirected_to_google():
    response = requests.get(f"{BASE}/api/drive/zip",
                            params={"url": drive_url(ROOT_ID)},
                            allow_redirects=False, timeout=60)

    assert response.status_code == 200
    assert "Location" not in response.headers


def test_download_works_with_the_daemon_stopped(stopped_daemon):
    """The reason this feature exists: it must not depend on the trainer's laptop."""
    response = requests.get(f"{BASE}/api/drive/zip",
                            params={"url": drive_url(ROOT_ID)}, timeout=60)

    assert response.status_code == 200
    assert zipfile.ZipFile(io.BytesIO(response.content)).namelist() == [
        "Intro.pdf", "Day 2/Lab.pdf",
    ]
```

There is NO docker-compose here and no `backend_url` fixture: the hermetic harness runs
backend, daemon and mock servers as processes inside ONE container, started by
`tests/docker/start_hermetic.sh`. Follow the conventions of the closest existing test,
`tests/docker/test_materials_zip.py`:

```python
BASE = "http://localhost:8000"
```

with plain `urllib.request` rather than `requests`, and `sys.path.insert(0, "/app")`.

For the daemon-offline scenario, do NOT stop a container. The relay never talks to the
daemon at all, so the honest assertion is that the endpoint answers while the daemon
process is not running. `tests/docker/test_session_end_daemon_reconnect.py` shows the
established pattern for stopping and restarting a process under test
(`proc.send_signal(signal.SIGTERM)`, then poll a health endpoint until it comes back).
Reuse that pattern rather than inventing another, and restore the daemon afterwards so
later tests in the same container are unaffected — a test that leaves the daemon dead
would fail every test that runs after it.

- [ ] **Step 3: Point the backend at the mock Drive**

Everything runs in one container on localhost, so this is an export in
`tests/docker/start_hermetic.sh`, next to the existing `MOCK_DRIVE_PORT` export:

```bash
export DRIVE_API_BASE_URL=http://localhost:${MOCK_DRIVE_PORT}/drive/v3
export GOOGLE_DRIVE_API_KEY=hermetic-test-key
export DRIVE_OWNER_EMAILS=victorrentea@gmail.com
```

These must be exported BEFORE the backend process is launched in that script, or the
backend will not see them.

- [ ] **Step 4: Run the hermetic tests**

Run: `bash tests/docker/run-hermetic.sh -k drive_relay -s`
Expected: PASS — all five tests, including the daemon-stopped one.

Do not mark this task complete on unit tests alone. This project requires Docker
tests to actually run in Docker.

- [ ] **Step 5: Commit**

```bash
git add tests/docker/mock_drive_server.py tests/docker/test_drive_relay.py \
        tests/docker/start_hermetic.sh
git commit -m "test(drive-relay): hermetic coverage incl. download with daemon stopped"
```

---

### Task 11: Documentation and rollout

**Files:**
- Modify: `API.md` (regenerated, never hand-edited)
- Modify: `ARCHITECTURE.md`
- Modify: `backlog.md`
- Modify: `CLAUDE.md` (env vars for production)

- [ ] **Step 1: Regenerate API.md**

```bash
uv run --extra dev python3 scripts/generate_apis_md.py --output API.md
```

Never edit `API.md` by hand — it is generated from the contracts.

- [ ] **Step 2: Update ARCHITECTURE.md**

Add the Drive relay to the C4 container/component diagrams: a Railway-side component
that talks to Google Drive directly and has **no** edge to the daemon. Make that
missing edge visible — it is the property that makes the feature work when the
trainer's laptop is closed.

- [ ] **Step 3: Record the feature in backlog.md**

Add an entry describing the request (participants on Drive-blocking networks) and what
shipped, following the existing format in that file.

- [ ] **Step 4: Document the production environment variables**

Add to the "Production Deployment" section of `CLAUDE.md`:

```markdown
- **Drive relay env** (Railway): `GOOGLE_DRIVE_API_KEY`, `DRIVE_OWNER_EMAILS`
  (and `DRIVE_OWNER_PERMISSION_IDS` if Google redacts owner emails for API-key
  requests — see the drive-relay spec). Changing `railway/**` triggers a real
  Railway deploy, unlike most changes here.
```

- [ ] **Step 5: Run the full check suite**

Run: `uv run --extra dev --extra daemon --extra telemetry bash tests/check-all.sh`
Expected: PASS

- [ ] **Step 6: Commit and push**

```bash
git add API.md ARCHITECTURE.md backlog.md CLAUDE.md
git commit -m "docs: document the Drive relay endpoints, architecture and config"
git push origin master
```

- [ ] **Step 7: Verify in production**

After Railway finishes deploying (this change touches `railway/**`, so a real deploy
does happen), set the environment variables in Railway, then:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://interact.victorrentea.ro/drive
curl -s "https://interact.victorrentea.ro/api/drive/preview?url=https://example.com/x"
```
Expected: `200` for the page; `{"detail":"That doesn't look like a Google Drive link"}`
for the second. Then paste a real folder link on the page and confirm the zip downloads
and opens.

The task is not done until production is confirmed live.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| Link parsing (all URL shapes) | 2 |
| Drive client, API key, pagination, native export, shortcuts | 3, 5 |
| Ownership gate, redaction fallback | 1, 4 |
| Exclusions (`attendees.md`, `session-state.json`, `.obsidian/`; `*.zip` kept) | 4b, 5 |
| Recursion, structure, trashed, shortcuts, dedup | 5 |
| Streaming zip, STORED, constant memory, no disk | 6 |
| 500 MB cap, checked twice, `has_unsized_files` | 5 (plan), 7 (pre-check), 6+8 (mid-stream) |
| Preview endpoint | 7 |
| Single-file link streams directly | 8 |
| Error table and exact copy | 7, 8 |
| Not-owned and missing are indistinguishable (both 404) | 7 |
| Page, three states, disabled button | 9 |
| Rate limiting, logging | 8 |
| No browser-to-Google traffic | 8 (no-redirect test), 9 (page content test), 10 (hermetic) |
| Works with daemon offline / no session | 7, 10 |
| Route ordering vs `/{session_id}` | 7 |
| Setup, env vars, deploy note | 1, 11 |

**Placeholders:** none — every step carries the code or command it needs. Task 1 is
inherently manual (it needs a credential only Victor can create) and says exactly which
commands to run and how each outcome changes the configuration.

**Type consistency:** `DriveFile`/`DriveOwner` field names are used identically in Tasks
3–8; `TransferPlan.known_bytes`/`has_unsized_files` match between Task 5, the preview
response in Task 7, and the page's `body.has_unsized_files` in Task 9;
`MAX_TRANSFER_BYTES` is defined once in Task 7's router and consumed in Task 8.

**Known soft spots to watch during execution:**

1. Task 10's harness was corrected after inspection: there is no docker-compose and no
   `backend_url` fixture. Backend, daemon and mocks run as processes in one container
   started by `tests/docker/start_hermetic.sh`; tests use `BASE = "http://localhost:8000"`
   and stdlib `urllib`, per `tests/docker/test_materials_zip.py`.
2. Task 8's rate-limit tests need `_EXEMPT_PEERS` neutralised because `TestClient`
   looks like loopback; the note is in the task but is easy to skip.
3. If Task 1 finds no usable owner identity, Task 4's gate cannot work as written and
   the `DRIVE_ALLOWED_ROOT_IDS` fallback becomes a real task in `tree.py`. That is the
   one outcome that changes the plan's shape.
