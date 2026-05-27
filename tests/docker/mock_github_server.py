"""
Mock GitHub HTTP stub server for hermetic testing.

Serves deterministic responses for GitHub API + blob HEAD verification calls so
the daemon's github_client.py never hits the real GitHub network.

Routes:
  GET  /repos/{owner}/{repo}          → 200 {"default_branch": "..."} if seeded, else 404
  HEAD /{owner}/{repo}/blob/{branch}/{path:rest} → 200 if seeded with status=200, else 404
  POST /__seed  body: {"repos": [...], "blobs": [...]}  → seed in-memory state
  POST /__reset → clear all state

Seed format:
  repos: [{"owner": "...", "repo": "...", "status": 200, "default_branch": "..."}]
  blobs: [{"owner": "...", "repo": "...", "path": "...", "status": 200}]

Note: only repos with status=200 are seeded as public; absent repos return 404.
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

MOCK_GITHUB_PORT = int(os.environ.get("MOCK_GITHUB_PORT", "9091"))

# In-memory state. Key: (owner, repo) → {"default_branch": "..."}
_repos: dict[tuple[str, str], dict] = {}
# Key: (owner, repo, path) → True (200) or False (404)
_blobs: dict[tuple[str, str, str], bool] = {}
_lock = threading.Lock()


class MockGitHubHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        # /repos/{owner}/{repo}
        parts = self.path.lstrip("/").split("/")
        if len(parts) >= 3 and parts[0] == "repos":
            owner = parts[1]
            repo = parts[2]
            with _lock:
                entry = _repos.get((owner, repo))
            if entry is None:
                self._send_json(404, {"message": "Not Found"})
            else:
                self._send_json(200, {"default_branch": entry["default_branch"], "full_name": f"{owner}/{repo}"})
            return
        self._send_json(404, {"message": "Not Found"})

    def do_HEAD(self):
        # /{owner}/{repo}/blob/{branch}/{path...}
        # path may contain slashes
        stripped = self.path.lstrip("/")
        parts = stripped.split("/")
        # Need at least: owner / repo / blob / branch / file
        if len(parts) >= 5 and parts[2] == "blob":
            owner = parts[0]
            repo = parts[1]
            # branch = parts[3]  (not used for lookup — any branch accepted)
            file_path = "/".join(parts[4:])
            with _lock:
                exists = _blobs.get((owner, repo, file_path), False)
            if exists:
                self._send_empty(200)
            else:
                self._send_empty(404)
            return
        self._send_empty(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(body_bytes)
        except Exception:
            body = {}

        if self.path == "/__reset":
            with _lock:
                _repos.clear()
                _blobs.clear()
            print("[mock-github] State reset")
            self._send_json(200, {"ok": True})
            return

        if self.path == "/__seed":
            repos_data = body.get("repos", [])
            blobs_data = body.get("blobs", [])
            with _lock:
                for r in repos_data:
                    if r.get("status", 200) == 200:
                        key = (r["owner"], r["repo"])
                        _repos[key] = {"default_branch": r.get("default_branch", "main")}
                for b in blobs_data:
                    key = (b["owner"], b["repo"], b["path"])
                    _blobs[key] = b.get("status", 200) == 200
            print(f"[mock-github] Seeded {len(repos_data)} repos, {len(blobs_data)} blobs")
            self._send_json(200, {"ok": True})
            return

        self._send_json(404, {"message": "Not Found"})

    def _send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, code: int) -> None:
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress default access log to keep output clean
        pass


def start_mock_github(port: int = MOCK_GITHUB_PORT) -> HTTPServer:
    server = HTTPServer(("0.0.0.0", port), MockGitHubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[mock-github] Serving on port {port}")
    return server


if __name__ == "__main__":
    _app_dir = "/app"
    if _app_dir not in sys.path:
        sys.path.insert(0, _app_dir)

    server = start_mock_github()
    print(f"[mock-github] Running on http://0.0.0.0:{MOCK_GITHUB_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
