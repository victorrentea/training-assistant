"""SlidesOnDemandWsRunner — send slides catalog and handle slide_log messages over a persistent WebSocket."""

import base64
import json
import os
import re
import ssl
import threading
import time
from pathlib import Path

from websockets.sync.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

from daemon import log
from daemon.session_state import resolve_materials_folder

_SLIDES_ON_DEMAND_WS_RECONNECT_SECONDS = 3.0
_DEFAULT_MATERIALS_FOLDER = Path("/Users/victorrentea/Documents/workshop-materials")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "slide"


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


class SlidesOnDemandWsRunner:
    """Send slides catalog to backend and handle slide_log messages over a persistent WebSocket."""

    def __init__(self, main_config):
        self.main_config = main_config
        self.enabled = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._slug_map: dict[str, tuple[Path, str]] = {}
        self._slides_dirs: list[Path] = []
        self._current_ws = None
        self._ws_lock = threading.Lock()

    def send_message(self, msg: dict) -> bool:
        """Send a message over the current WS connection. Returns True if sent, False if not connected."""
        with self._ws_lock:
            ws = self._current_ws
        if ws is None:
            return False
        try:
            ws.send(json.dumps(msg))
            return True
        except Exception as exc:
            log.error("slides", f"send_message failed: {exc}")
            return False

    def start(self) -> None:
        enabled_raw = os.environ.get("SLIDES_ON_DEMAND_UPLOAD_ENABLED", "1").strip().lower()
        if enabled_raw in {"0", "false", "no", "off"}:
            log.info("slides", "On-demand WS disabled by SLIDES_ON_DEMAND_UPLOAD_ENABLED")
            self.enabled = False
            return

        self._slides_dirs = self._candidate_slides_dirs()
        if self._slides_dirs:
            joined = ", ".join(str(p) for p in self._slides_dirs)
            log.info("slides", f"On-demand WS slide dirs: {joined}")
        else:
            log.info("slides", "On-demand WS: no local slide dir detected at startup (will keep retrying)")
        self._rebuild_slug_map()
        self.enabled = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self.enabled:
            return
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _catalog_path(self) -> Path:
        configured = os.environ.get("PPTX_CATALOG_FILE", "").strip()
        if configured:
            return Path(configured).expanduser()
        return Path(__file__).parent.parent / "materials_slides_catalog.json"

    def _candidate_slides_dirs(self) -> list[Path]:
        candidates: list[Path] = []
        env_slides = os.environ.get("TRAINING_ASSISTANT_SLIDES_DIR", "").strip()
        env_publish = os.environ.get("PPTX_PUBLISH_DIR", "").strip()
        env_materials = os.environ.get("MATERIALS_FOLDER", "").strip()
        if env_slides:
            candidates.append(Path(env_slides).expanduser())
        if env_publish:
            candidates.append(Path(env_publish).expanduser())
        if env_materials:
            candidates.append(Path(env_materials).expanduser() / "slides")

        resolved_materials = resolve_materials_folder()
        if resolved_materials is not None:
            candidates.append(resolved_materials / "slides")

        candidates.extend([
            Path(__file__).parent.parent.parent / "materials" / "slides",
            Path.cwd() / "materials" / "slides",
            Path.home() / "workspace" / "training-assistant" / "materials" / "slides",
            _DEFAULT_MATERIALS_FOLDER / "slides",
        ])

        seen: set[str] = set()
        dirs: list[Path] = []
        for candidate in candidates:
            key = str(candidate.resolve()) if candidate.exists() else str(candidate)
            if key in seen:
                continue
            seen.add(key)
            if candidate.exists() and candidate.is_dir():
                dirs.append(candidate)
        return dirs

    def _rebuild_slug_map(self) -> None:
        self._slug_map = {}
        self._slides_dirs = self._candidate_slides_dirs()

        catalog_path = self._catalog_path()
        if catalog_path.exists():
            try:
                raw = json.loads(catalog_path.read_text(encoding="utf-8"))
                entries = raw.get("decks", []) if isinstance(raw, dict) else []
                if isinstance(entries, list):
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        target_pdf = str(entry.get("target_pdf") or "").strip()
                        if not target_pdf:
                            continue
                        if not target_pdf.lower().endswith(".pdf"):
                            target_pdf += ".pdf"
                        explicit_slug = str(entry.get("slug") or "").strip().lower()
                        slug = explicit_slug or _slugify(Path(target_pdf).stem)
                        local_pdf = None
                        for slides_dir in self._slides_dirs:
                            candidate = slides_dir / target_pdf
                            if candidate.exists() and candidate.is_file():
                                local_pdf = candidate
                                break
                        if local_pdf is None and self._slides_dirs:
                            local_pdf = self._slides_dirs[0] / target_pdf
                        if local_pdf is None:
                            continue
                        if slug in self._slug_map:
                            continue
                        source_pptx = Path(str(entry.get("source") or "").strip()) if entry.get("source") else None
                        self._slug_map[slug] = (local_pdf, target_pdf, source_pptx)
            except Exception as exc:
                log.error("slides", f"On-demand catalog parse failed: {exc}")

        for slides_dir in self._slides_dirs:
            for pdf in sorted(slides_dir.glob("*.pdf"), key=lambda p: p.name.lower()):
                slug = _slugify(pdf.stem)
                self._slug_map.setdefault(slug, (pdf, pdf.name, None))

    def _ws_url(self) -> str:
        base = self.main_config.server_url.rstrip("/")
        if base.startswith("https://"):
            base = "wss://" + base[len("https://"):]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://"):]
        return f"{base}/ws/daemon"

    def _auth_headers(self) -> dict[str, str]:
        token = base64.b64encode(
            f"{self.main_config.host_username}:{self.main_config.host_password}".encode("utf-8")
        ).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    def _send_slides_catalog(self, ws) -> None:
        """Send full catalog with drive_export_url to backend."""
        try:
            catalog_path = self._catalog_path()
            if not catalog_path.exists():
                log.info("slides", "slides_catalog: no catalog file found")
                return
            data = json.loads(catalog_path.read_text(encoding="utf-8"))
            entries = []
            for deck in data.get("decks", []):
                target_pdf_val = deck.get("target_pdf", "")
                slug = deck.get("slug") or (
                    _slugify(Path(target_pdf_val).stem) if target_pdf_val
                    else _slugify(deck.get("title", ""))
                )
                url = deck.get("drive_export_url", "")
                if slug and url:
                    entry = {"slug": slug, "title": deck.get("title", slug), "drive_export_url": url}
                    source = deck.get("source", "")
                    if source:
                        src_path = Path(source)
                        if src_path.exists():
                            from datetime import datetime, timezone
                            entry["updated_at"] = datetime.fromtimestamp(
                                src_path.stat().st_mtime, tz=timezone.utc
                            ).isoformat()
                    entries.append(entry)
            ws.send(json.dumps({"type": "slides_catalog", "entries": entries}))
            log.info("slides", f"slides_catalog sent: {len(entries)} entries")
        except Exception as exc:
            log.error("slides", f"slides_catalog_send_failed: {exc}")

    def _handle_request(self, ws, payload: dict) -> None:
        if payload.get("type") == "slide_log":
            slug = payload.get("slug", "?")
            event = payload.get("event", "?")
            detail = payload.get("detail", "")
            log_detail = "" if event == "download_start" else detail
            log.info("slides", f"📡 {event} slug={slug}" + (f" {log_detail}" if log_detail else ""))
            return

    def _run_loop(self) -> None:
        ws_url = self._ws_url()
        headers = self._auth_headers()
        while not self._stop.is_set():
            try:
                with self._connect(ws_url, headers) as ws:
                    with self._ws_lock:
                        self._current_ws = ws
                    try:
                        log.info("slides", f"slides_ws_connected to {ws_url}")
                        self._send_slides_catalog(ws)
                        while not self._stop.is_set():
                            try:
                                raw = ws.recv(timeout=1.0)
                            except TimeoutError:
                                continue
                            except ConnectionClosed:
                                break
                            try:
                                payload = json.loads(raw)
                            except Exception:
                                continue
                            self._handle_request(ws, payload)
                    finally:
                        with self._ws_lock:
                            self._current_ws = None
            except Exception as exc:
                if not self._stop.is_set():
                    log.error("slides", f"slides_ws_connect_failed: {exc}")
                    time.sleep(_SLIDES_ON_DEMAND_WS_RECONNECT_SECONDS)

    @staticmethod
    def _connect(ws_url: str, headers: dict[str, str]):
        # websockets changed auth-header kwarg name across versions.
        # Try modern API first, then fallback for older clients.
        ws_kwargs = {
            "open_timeout": 10,
            "ping_interval": 20,
            "ping_timeout": 20,
        }
        if ws_url.startswith("wss://"):
            ws_kwargs["ssl"] = _ssl_context()
        try:
            return ws_connect(
                ws_url,
                additional_headers=headers,
                **ws_kwargs,
            )
        except TypeError as exc:
            message = str(exc)
            if "additional_headers" not in message:
                raise
            return ws_connect(
                ws_url,
                extra_headers=headers,
                **ws_kwargs,
            )
