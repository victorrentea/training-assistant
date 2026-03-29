"""
Google Drive URL extraction, fingerprinting, and PDF download helpers.
"""

from __future__ import annotations

import hashlib
import html.parser
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from daemon.slides.daemon import _ssl_context


class _SlidesLinksHTMLParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._current_href: str | None = None
        self._current_text_parts: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._current_href = href.strip()
            self._current_text_parts = []

    def handle_data(self, data: str) -> None:
        if self._current_href is None:
            return
        self._current_text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._current_href is None:
            return
        text = "".join(self._current_text_parts).strip()
        if text:
            self.links.append((text, self._current_href))
        self._current_href = None
        self._current_text_parts = []


def _read_url_text(url: str, timeout: float = 20.0) -> str:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _to_drive_export_pdf_url(href: str) -> str | None:
    parsed = urllib.parse.urlparse(href)
    if not parsed.scheme:
        return None
    host = parsed.netloc.lower()
    path = parsed.path
    if "docs.google.com" in host:
        m = re.search(r"/presentation/d/([^/]+)", path)
        if m:
            return f"https://docs.google.com/presentation/d/{m.group(1)}/export/pdf"
    if "drive.google.com" in host:
        m = re.search(r"/file/d/([^/]+)", path)
        if m:
            return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return None


def extract_drive_export_links(html_text: str) -> dict[str, str]:
    parser = _SlidesLinksHTMLParser()
    parser.feed(html_text)
    links: dict[str, str] = {}
    for title, href in parser.links:
        export_url = _to_drive_export_pdf_url(href)
        if export_url:
            links[title] = export_url
    return links


def _beep_local() -> None:
    from daemon.adapters.loader import adapter
    adapter.beep()


def _is_google_drive_running() -> bool:
    from daemon.adapters.loader import adapter
    return adapter.is_google_drive_running()


def _probe_drive_fingerprint(url: str) -> tuple[str, dict[str, str]]:
    head_req = urllib.request.Request(url, method="HEAD")
    response_headers: dict[str, str] = {}
    body_hash: str | None = None

    try:
        with urllib.request.urlopen(head_req, timeout=20, context=_ssl_context()) as response:
            response_headers = {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        if exc.code != 405:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"drive_url_error: HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"drive_url_error: {exc}") from exc

    etag = response_headers.get("etag", "").strip()
    last_modified = response_headers.get("last-modified", "").strip()
    content_length = response_headers.get("content-length", "").strip()
    if etag or last_modified or content_length:
        return f"hdr:{etag}|{last_modified}|{content_length}", response_headers

    get_req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(get_req, timeout=30, context=_ssl_context()) as response:
            response_headers = {k.lower(): v for k, v in response.headers.items()}
            payload = response.read()
            body_hash = hashlib.sha256(payload).hexdigest()
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"drive_url_error: HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"drive_url_error: {exc}") from exc

    return f"body:{body_hash}", response_headers


def _download_pdf_from_url(url: str, output_pdf: Path) -> Path:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"drive_url_error: HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"drive_url_error: {exc}") from exc

    if not payload or not payload.startswith(b"%PDF-"):
        raise RuntimeError("invalid_pdf_payload: Downloaded content is not a PDF file")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    output_pdf.write_bytes(payload)
    return output_pdf
