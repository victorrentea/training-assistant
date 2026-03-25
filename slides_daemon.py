#!/usr/bin/env python3
"""
PPTX Slides Daemon.

Watches a local folder for .pptx changes, exports to PDF, uploads with an
obfuscated slug URL, and notifies the workshop backend.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SERVER_URL = "http://localhost:8000"
DEFAULT_POLL_SECONDS = 30.0
DEFAULT_MIN_CPU_FREE = 25.0


def load_secrets_env() -> None:
    """Load key=value pairs from secrets.env into environment once."""
    path = Path(__file__).parent / "secrets.env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass
class SlidesDaemonConfig:
    watch_dir: Path
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


def config_from_env() -> SlidesDaemonConfig:
    load_secrets_env()
    watch_dir = Path(os.environ.get("PPTX_WATCH_DIR", "")).expanduser()
    if not watch_dir:
        raise RuntimeError("PPTX_WATCH_DIR is required")
    if not watch_dir.exists() or not watch_dir.is_dir():
        raise RuntimeError(f"PPTX_WATCH_DIR not found: {watch_dir}")

    poll_interval = float(os.environ.get("PPTX_DAEMON_POLL_SECONDS", str(DEFAULT_POLL_SECONDS)))
    min_cpu_free = float(os.environ.get("PPTX_MIN_CPU_FREE_PERCENT", str(DEFAULT_MIN_CPU_FREE)))
    state_file = Path(
        os.environ.get("PPTX_DAEMON_STATE_FILE", str(Path(".context") / "pptx_daemon_state.json"))
    ).expanduser()
    work_dir = Path(os.environ.get("PPTX_DAEMON_WORK_DIR", str(Path(".context") / "pptx_daemon_work"))).expanduser()

    server_url = os.environ.get("WORKSHOP_SERVER_URL", DEFAULT_SERVER_URL).rstrip("/")
    host_username = os.environ.get("HOST_USERNAME", "host")
    host_password = os.environ.get("HOST_PASSWORD", "")
    converter = os.environ.get("PPTX_CONVERTER", "google_drive").strip().lower()
    upload_mode = os.environ.get("PPTX_UPLOAD_MODE", "copy").strip().lower()
    public_base_url = os.environ.get("PPTX_PUBLIC_BASE_URL", "").rstrip("/")
    publish_dir = Path(os.environ.get("PPTX_PUBLISH_DIR", str(Path(".context") / "published-slides"))).expanduser()
    recursive = os.environ.get("PPTX_RECURSIVE", "0").strip() in {"1", "true", "yes"}

    if not public_base_url:
        raise RuntimeError("PPTX_PUBLIC_BASE_URL is required")

    return SlidesDaemonConfig(
        watch_dir=watch_dir,
        poll_interval_seconds=max(1.0, poll_interval),
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
        with urllib.request.urlopen(req, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to reach {url}: {exc}") from exc


def load_daemon_state(path: Path) -> dict:
    if not path.exists():
        return {"files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        files = data.get("files", {})
        if isinstance(files, dict):
            return {"files": files}
    except Exception:
        pass
    return {"files": {}}


def save_daemon_state(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def list_pptx_files(folder: Path, recursive: bool) -> list[Path]:
    pattern_iter = folder.rglob("*") if recursive else folder.iterdir()
    files = [
        p for p in pattern_iter
        if p.is_file() and p.suffix.lower() == ".pptx"
    ]
    files.sort(key=lambda p: p.name.lower())
    return files


def _abs_key(path: Path) -> str:
    return str(path.expanduser().resolve())


def detect_changed_files(files: list[Path], daemon_state: dict) -> list[Path]:
    changed: list[tuple[float, Path]] = []
    tracked = daemon_state.setdefault("files", {})
    for pptx in files:
        key = _abs_key(pptx)
        exported_mtime = float(tracked.get(key, {}).get("last_exported_mtime", 0))
        current_mtime = pptx.stat().st_mtime
        if current_mtime > exported_mtime:
            changed.append((current_mtime, pptx))
    changed.sort(key=lambda x: x[0])
    return [p for _, p in changed]


def ensure_slug(daemon_state: dict, pptx_path: Path) -> str:
    key = _abs_key(pptx_path)
    tracked = daemon_state.setdefault("files", {})
    entry = tracked.setdefault(key, {})
    slug = entry.get("slug")
    if slug:
        return slug
    slug = uuid.uuid4().hex
    entry["slug"] = slug
    return slug


def get_cpu_free_percent(sample_seconds: float = 1.0) -> float:
    """Returns estimated free CPU percentage."""
    try:
        import psutil  # type: ignore

        busy = float(psutil.cpu_percent(interval=sample_seconds))
        return max(0.0, min(100.0, 100.0 - busy))
    except Exception:
        if sample_seconds > 0:
            time.sleep(sample_seconds)
        load_1m = os.getloadavg()[0]
        cores = max(1, os.cpu_count() or 1)
        busy_pct = min(100.0, (load_1m / cores) * 100.0)
        return max(0.0, 100.0 - busy_pct)


def convert_with_libreoffice(pptx_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "soffice",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(pptx_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"LibreOffice conversion failed: {proc.stderr.strip() or proc.stdout.strip()}")
    pdf_path = output_dir / f"{pptx_path.stem}.pdf"
    if not pdf_path.exists():
        raise RuntimeError(f"Expected PDF not found: {pdf_path}")
    return pdf_path


def convert_with_google_drive(pptx_path: Path, output_pdf: Path) -> Path:
    """Upload PPTX to Google Drive and export as PDF."""
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not credentials_path:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS is required for google_drive converter")

    try:
        from google.oauth2 import service_account  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
        from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "google_drive converter requires google-api-python-client and google-auth"
        ) from exc

    creds = service_account.Credentials.from_service_account_file(
        credentials_path,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    file_id = None
    try:
        meta = {"name": pptx_path.name, "mimeType": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
        uploaded = service.files().create(
            body=meta,
            media_body=MediaFileUpload(str(pptx_path), mimetype=meta["mimeType"], resumable=False),
            fields="id",
        ).execute()
        file_id = uploaded["id"]

        request = service.files().export_media(fileId=file_id, mimeType="application/pdf")
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        with output_pdf.open("wb") as target:
            downloader = MediaIoBaseDownload(target, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
    finally:
        if file_id:
            try:
                service.files().delete(fileId=file_id).execute()
            except Exception:
                pass
    return output_pdf


def convert_pptx_to_pdf(pptx_path: Path, config: SlidesDaemonConfig, slug: str) -> Path:
    work_pdf = config.work_dir / f"{slug}.pdf"
    if config.converter == "google_drive":
        return convert_with_google_drive(pptx_path, work_pdf)
    if config.converter == "libreoffice":
        converted = convert_with_libreoffice(pptx_path, config.work_dir)
        if converted != work_pdf:
            shutil.copy2(converted, work_pdf)
        return work_pdf
    raise RuntimeError(f"Unknown PPTX_CONVERTER: {config.converter}")


def upload_pdf(pdf_path: Path, slug: str, config: SlidesDaemonConfig) -> str:
    target_name = f"{slug}.pdf"

    if config.upload_mode == "copy":
        config.publish_dir.mkdir(parents=True, exist_ok=True)
        target_path = config.publish_dir / target_name
        shutil.copy2(pdf_path, target_path)
        return f"{config.public_base_url}/{target_name}"

    if config.upload_mode == "scp":
        target_dir = os.environ.get("PPTX_SCP_TARGET", "").strip()
        if not target_dir:
            raise RuntimeError("PPTX_SCP_TARGET is required for scp upload mode")
        remote_target = target_dir.rstrip("/") + "/" + target_name
        proc = subprocess.run(
            ["scp", str(pdf_path), remote_target],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"scp upload failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return f"{config.public_base_url}/{target_name}"

    if config.upload_mode == "http_put":
        template = os.environ.get("PPTX_UPLOAD_URL_TEMPLATE", "").strip()
        if not template:
            raise RuntimeError("PPTX_UPLOAD_URL_TEMPLATE is required for http_put mode")
        upload_url = template.format(slug=slug, filename=target_name)
        token = os.environ.get("PPTX_UPLOAD_BEARER_TOKEN", "").strip()
        headers = {"Content-Type": "application/pdf"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(
            upload_url,
            data=pdf_path.read_bytes(),
            method="PUT",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=30):
                pass
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP PUT upload failed with status {exc.code}") from exc
        return f"{config.public_base_url}/{target_name}"

    raise RuntimeError(f"Unknown PPTX_UPLOAD_MODE: {config.upload_mode}")


def push_current_slides(config: SlidesDaemonConfig, public_url: str, slug: str, source_file: str) -> None:
    payload = {
        "url": public_url,
        "slug": slug,
        "source_file": source_file,
        "converter": config.converter,
    }
    _post_json(
        f"{config.server_url}/api/slides/current",
        payload,
        config.host_username,
        config.host_password,
    )


def process_one_file(config: SlidesDaemonConfig, daemon_state: dict, pptx_path: Path) -> bool:
    cpu_free = get_cpu_free_percent(sample_seconds=1.0)
    if cpu_free < config.min_cpu_free_percent:
        print(
            f"[pptx-daemon] CPU overloaded ({cpu_free:.1f}% free < "
            f"{config.min_cpu_free_percent:.0f}% threshold) -- skipping PDF export",
            flush=True,
        )
        return False

    slug = ensure_slug(daemon_state, pptx_path)
    pdf_path = convert_pptx_to_pdf(pptx_path, config, slug)
    public_url = upload_pdf(pdf_path, slug, config)
    push_current_slides(config, public_url, slug, pptx_path.name)

    key = _abs_key(pptx_path)
    daemon_state.setdefault("files", {}).setdefault(key, {})
    daemon_state["files"][key]["slug"] = slug
    daemon_state["files"][key]["last_exported_mtime"] = pptx_path.stat().st_mtime
    save_daemon_state(config.state_file, daemon_state)
    print(f"[pptx-daemon] Published {pptx_path.name} -> {public_url}", flush=True)
    return True


def run_once(config: SlidesDaemonConfig, daemon_state: dict) -> bool:
    files = list_pptx_files(config.watch_dir, recursive=config.recursive)
    changed = detect_changed_files(files, daemon_state)
    if not changed:
        return False
    # serialize: process one file per poll cycle
    return process_one_file(config, daemon_state, changed[0])


def run_forever(config: SlidesDaemonConfig) -> None:
    daemon_state = load_daemon_state(config.state_file)
    print(
        f"[pptx-daemon] Watching {config.watch_dir} every {config.poll_interval_seconds:.0f}s "
        f"(converter={config.converter}, upload={config.upload_mode})",
        flush=True,
    )
    while True:
        try:
            run_once(config, daemon_state)
        except Exception as exc:
            print(f"[pptx-daemon] ERROR: {exc}", file=sys.stderr, flush=True)
        time.sleep(config.poll_interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Watch PPTX files and publish exported PDFs.")
    parser.add_argument("--once", action="store_true", help="Run one poll cycle and exit")
    args = parser.parse_args(argv)

    try:
        config = config_from_env()
    except Exception as exc:
        print(f"[pptx-daemon] Config error: {exc}", file=sys.stderr, flush=True)
        return 1

    daemon_state = load_daemon_state(config.state_file)
    if args.once:
        try:
            changed = run_once(config, daemon_state)
            return 0 if changed else 0
        except Exception as exc:
            print(f"[pptx-daemon] ERROR: {exc}", file=sys.stderr, flush=True)
            return 1

    run_forever(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
