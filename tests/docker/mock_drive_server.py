"""
Mock Google Drive HTTP server for hermetic testing.

Serves fixture PDFs at URLs that look like Google Drive export URLs.
Tracks request counts per slug for deduplication assertions.

Routes:
  GET  /presentation/d/{slug}/export/pdf → fixture PDF bytes
  HEAD /presentation/d/{slug}/export/pdf → headers only (etag, content-length)
  GET  /mock-drive/stats                 → {slug: request_count} JSON
  POST /mock-drive/reset-stats           → reset request counters
"""

import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

FIXTURE_DIR = os.environ.get("FIXTURE_PDF_DIR", "/tmp/fixture-pdfs")
MOCK_DRIVE_PORT = int(os.environ.get("MOCK_DRIVE_PORT", "9090"))

_request_counts: dict[str, int] = {}
_delays: dict[str, float] = {}   # slug → seconds to sleep before responding
_lock = threading.Lock()

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


class MockDriveHandler(BaseHTTPRequestHandler):
    def _parse_slug(self) -> str | None:
        # /presentation/d/{slug}/export/pdf
        parts = self.path.split("/")
        if len(parts) >= 5 and parts[1] == "presentation" and parts[2] == "d" and parts[4] == "export":
            return parts[3]
        return None

    def _get_pdf_path(self, slug: str) -> Path | None:
        path = Path(FIXTURE_DIR) / f"{slug}.pdf"
        return path if path.exists() else None

    def do_HEAD(self):
        slug = self._parse_slug()
        if not slug:
            self.send_error(404)
            return
        pdf_path = self._get_pdf_path(slug)
        if not pdf_path:
            self.send_error(404, f"No fixture PDF for slug: {slug}")
            return

        data = pdf_path.read_bytes()
        etag = hashlib.md5(data).hexdigest()

        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("ETag", f'"{etag}"')
        self.end_headers()

    def do_GET(self):
        # Stats endpoint
        if self.path == "/mock-drive/stats":
            with _lock:
                body = json.dumps(_request_counts).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

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

        slug = self._parse_slug()
        if not slug:
            self.send_error(404)
            return
        pdf_path = self._get_pdf_path(slug)
        if not pdf_path:
            self.send_error(404, f"No fixture PDF for slug: {slug}")
            return

        from opentelemetry import trace
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

        carrier = {k.lower(): v for k, v in self.headers.items()}
        ctx = TraceContextTextMapPropagator().extract(carrier=carrier)
        tracer = trace.get_tracer("mock-drive")
        with tracer.start_as_current_span(f"GET {slug}.pdf", context=ctx):
            # Track request and capture delay under lock
            with _lock:
                _request_counts[slug] = _request_counts.get(slug, 0) + 1
                count = _request_counts[slug]
                delay = _delays.get(slug, 0.0)

            if delay > 0:
                print(f"[mock-drive] GET {slug}.pdf — sleeping {delay}s to simulate slow Drive")
                time.sleep(delay)

            data = pdf_path.read_bytes()
            etag = hashlib.md5(data).hexdigest()

            print(f"[mock-drive] GET {slug}.pdf ({len(data)} bytes, request #{count})")

            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("ETag", f'"{etag}"')
            self.end_headers()
            self.wfile.write(data)

    def do_POST(self):
        if self.path == "/mock-drive/reset-stats":
            with _lock:
                _request_counts.clear()
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        if self.path == "/mock-drive/set-delay":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            slug = body.get("slug", "")
            delay_s = float(body.get("delay_s", 0))
            with _lock:
                if delay_s > 0:
                    _delays[slug] = delay_s
                else:
                    _delays.pop(slug, None)
            print(f"[mock-drive] delay for '{slug}' set to {delay_s}s")
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        if self.path == "/mock-drive/reset-delays":
            with _lock:
                _delays.clear()
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        self.send_error(404)

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

    def log_message(self, format, *args):
        # Suppress default logging to keep output clean
        pass


def start_mock_drive(port: int = MOCK_DRIVE_PORT) -> HTTPServer:
    server = HTTPServer(("0.0.0.0", port), MockDriveHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[mock-drive] Serving fixture PDFs on port {port}")
    return server


if __name__ == "__main__":
    # Ensure daemon package is importable for telemetry setup
    _app_dir = "/app"
    if _app_dir not in sys.path:
        sys.path.insert(0, _app_dir)

    os.environ.setdefault("OTEL_SERVICE_NAME", "GDrive")
    from daemon.telemetry import setup_tracing
    setup_tracing()

    server = start_mock_drive()
    print(f"[mock-drive] Running on http://0.0.0.0:{MOCK_DRIVE_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
