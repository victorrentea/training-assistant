#!/usr/bin/env python3
"""
PPTX Slides Daemon — config, secrets, and HTTP helpers.
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from daemon import log


DEFAULT_SERVER_URL = "http://localhost:8000"
DEFAULT_POLL_SECONDS = 5.0
DEFAULT_MIN_CPU_FREE = 25.0
DEFAULT_POST_EXPORT_COOLDOWN_SECONDS = 5.0
DEFAULT_FAILURE_RETRY_SECONDS = 60.0
DEFAULT_MATERIALS_FOLDER = Path("/Users/victorrentea/Documents/workshop-materials")
DEFAULT_DRIVE_SYNC_TIMEOUT_SECONDS = 300.0
DEFAULT_DRIVE_POLL_SECONDS = 5.0
DEFAULT_DRIVE_STABLE_PROBES = 2
DEFAULT_DRIVE_BOOTSTRAP_URL = "https://victorrentea.ro/slides/"

TITLE_ALIASES: dict[str, str] = {
    "Reactive/WebFlux": "Reactive WebFlux",
}


def load_secrets_env() -> None:
    """Load key=value pairs from the shared secrets file into environment once."""
    default_path = Path.home() / ".training-assistants-secrets.env"
    path = Path(
        os.environ.get("TRAINING_ASSISTANTS_SECRETS_FILE", str(default_path))
    ).expanduser()
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


@dataclass
class SlidesDaemonConfig:
    watch_dir: Path | None
    poll_interval_seconds: float
    min_cpu_free_percent: float
    state_file: Path
    work_dir: Path
    server_url: str
    host_username: str
    host_password: str
    converter: str
    upload_mode: str
    public_base_url: str
    publish_dir: Path
    recursive: bool
    post_export_cooldown_seconds: float
    failure_retry_seconds: float
    drive_sync_timeout_seconds: float
    drive_poll_seconds: float
    drive_stable_probes: int
    drive_bootstrap_url: str
    catalog_file: Path | None = None
    sync_backend: bool = True


def config_from_env() -> SlidesDaemonConfig:
    load_secrets_env()
    watch_dir_raw = os.environ.get("PPTX_WATCH_DIR", "").strip()
    watch_dir = Path(watch_dir_raw).expanduser() if watch_dir_raw else None
    if watch_dir is not None and (not watch_dir.exists() or not watch_dir.is_dir()):
        raise RuntimeError(f"PPTX_WATCH_DIR not found: {watch_dir}")

    poll_interval = float(os.environ.get("PPTX_DAEMON_POLL_SECONDS", str(DEFAULT_POLL_SECONDS)))
    min_cpu_free = float(os.environ.get("PPTX_MIN_CPU_FREE_PERCENT", str(DEFAULT_MIN_CPU_FREE)))
    state_file = Path(
        os.environ.get("PPTX_DAEMON_STATE_FILE", str(Path(".server-data") / "pptx_daemon_state.json"))
    ).expanduser()
    work_dir = Path(
        os.environ.get("PPTX_DAEMON_WORK_DIR", str(Path(".server-data") / "pptx_daemon_work"))
    ).expanduser()

    server_url = os.environ.get("WORKSHOP_SERVER_URL", DEFAULT_SERVER_URL).rstrip("/")
    host_username = os.environ.get("HOST_USERNAME", "host")
    host_password = os.environ.get("HOST_PASSWORD", "")
    converter = os.environ.get("PPTX_CONVERTER", "google_drive_pull").strip().lower()
    upload_mode = os.environ.get("PPTX_UPLOAD_MODE", "copy").strip().lower()
    public_base_url = os.environ.get("PPTX_PUBLIC_BASE_URL", "").rstrip("/")
    default_materials_root = Path(
        os.environ.get("MATERIALS_FOLDER", str(DEFAULT_MATERIALS_FOLDER))
    ).expanduser()
    publish_dir = Path(
        os.environ.get("PPTX_PUBLISH_DIR", str(default_materials_root / "slides"))
    ).expanduser()
    recursive = os.environ.get("PPTX_RECURSIVE", "0").strip() in {"1", "true", "yes"}
    cooldown_raw = os.environ.get("PPTX_POST_EXPORT_COOLDOWN_SECONDS", str(DEFAULT_POST_EXPORT_COOLDOWN_SECONDS))
    post_export_cooldown = max(DEFAULT_POST_EXPORT_COOLDOWN_SECONDS, float(cooldown_raw))
    failure_retry_raw = os.environ.get("PPTX_FAILURE_RETRY_SECONDS", str(DEFAULT_FAILURE_RETRY_SECONDS))
    failure_retry_seconds = max(5.0, float(failure_retry_raw))
    drive_sync_timeout_raw = os.environ.get(
        "PPTX_DRIVE_SYNC_TIMEOUT_SECONDS",
        str(DEFAULT_DRIVE_SYNC_TIMEOUT_SECONDS),
    )
    drive_sync_timeout_seconds = max(10.0, float(drive_sync_timeout_raw))
    drive_poll_raw = os.environ.get("PPTX_DRIVE_POLL_SECONDS", str(DEFAULT_DRIVE_POLL_SECONDS))
    drive_poll_seconds = max(1.0, float(drive_poll_raw))
    stable_raw = os.environ.get("PPTX_DRIVE_STABLE_PROBES", str(DEFAULT_DRIVE_STABLE_PROBES))
    drive_stable_probes = max(1, int(stable_raw))
    drive_bootstrap_url = os.environ.get("PPTX_DRIVE_BOOTSTRAP_URL", DEFAULT_DRIVE_BOOTSTRAP_URL).strip()
    catalog_file_str = os.environ.get(
        "PPTX_CATALOG_FILE",
        str(Path(__file__).parent.parent.parent / "daemon" / "materials_slides_catalog.json"),
    ).strip()
    catalog_file = Path(catalog_file_str).expanduser() if catalog_file_str else None

    sync_env = os.environ.get("PPTX_SYNC_BACKEND")
    if sync_env is None:
        sync_backend = bool(public_base_url)
    else:
        sync_backend = sync_env.strip().lower() in {"1", "true", "yes"}
    if sync_backend and not public_base_url:
        raise RuntimeError("PPTX_PUBLIC_BASE_URL is required when PPTX_SYNC_BACKEND is enabled")
    if watch_dir is None and (catalog_file is None or not catalog_file.exists()):
        raise RuntimeError("Either PPTX_WATCH_DIR or a valid PPTX_CATALOG_FILE is required")
    if converter != "google_drive_pull":
        raise RuntimeError(
            "Only PPTX_CONVERTER=google_drive_pull is supported. "
            "Local conversion paths (LibreOffice / upload-export) were removed."
        )

    return SlidesDaemonConfig(
        watch_dir=watch_dir,
        poll_interval_seconds=max(0.1, poll_interval),
        min_cpu_free_percent=min_cpu_free,
        state_file=state_file,
        work_dir=work_dir,
        server_url=server_url,
        host_username=host_username,
        host_password=host_password,
        converter=converter,
        upload_mode=upload_mode,
        public_base_url=public_base_url,
        publish_dir=publish_dir,
        recursive=recursive,
        post_export_cooldown_seconds=post_export_cooldown,
        failure_retry_seconds=failure_retry_seconds,
        drive_sync_timeout_seconds=drive_sync_timeout_seconds,
        drive_poll_seconds=drive_poll_seconds,
        drive_stable_probes=drive_stable_probes,
        drive_bootstrap_url=drive_bootstrap_url,
        catalog_file=catalog_file,
        sync_backend=sync_backend,
    )


def _auth_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _post_json(url: str, payload: dict, username: str, password: str, timeout: float = 20.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": _auth_header(username, password),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as response:
            text = response.read().decode("utf-8", errors="replace")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to reach {url}: {exc}") from exc


def load_daemon_state(path: Path) -> dict:
    empty = {"files": {}, "last_slides_hash": None}
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        files = data.get("files", {})
        last_slides_hash = data.get("last_slides_hash")
        if isinstance(files, dict):
            return {
                "files": files,
                "last_slides_hash": last_slides_hash if isinstance(last_slides_hash, str) else None,
            }
    except Exception:
        pass
    return empty


def save_daemon_state(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)
