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
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path


FIXTURE_DIR = os.environ.get("FIXTURE_PDF_DIR", "/tmp/fixture-pdfs")
MOCK_DRIVE_PORT = int(os.environ.get("MOCK_DRIVE_PORT", "9090"))

_request_counts: dict[str, int] = {}
_lock = threading.Lock()


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

        slug = self._parse_slug()
        if not slug:
            self.send_error(404)
            return
        pdf_path = self._get_pdf_path(slug)
        if not pdf_path:
            self.send_error(404, f"No fixture PDF for slug: {slug}")
            return

        # Track request
        with _lock:
            _request_counts[slug] = _request_counts.get(slug, 0) + 1
            count = _request_counts[slug]

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
        self.send_error(404)

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
    server = start_mock_drive()
    print(f"[mock-drive] Running on http://0.0.0.0:{MOCK_DRIVE_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
