#!/usr/bin/env python3
"""
PPTX Slides Daemon.

Watches a local folder for .pptx changes, exports to PDF, uploads with an
obfuscated slug URL, and notifies the workshop backend.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_SERVER_URL = "http://localhost:8000"
DEFAULT_POLL_SECONDS = 5.0
DEFAULT_MIN_CPU_FREE = 25.0
DEFAULT_POST_EXPORT_COOLDOWN_SECONDS = 5.0
DEFAULT_FAILURE_RETRY_SECONDS = 60.0


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
    converter = os.environ.get("PPTX_CONVERTER", "libreoffice").strip().lower()
    upload_mode = os.environ.get("PPTX_UPLOAD_MODE", "copy").strip().lower()
    public_base_url = os.environ.get("PPTX_PUBLIC_BASE_URL", "").rstrip("/")
    default_materials_root = Path(
        os.environ.get("MATERIALS_FOLDER", str(Path(__file__).parent / "materials"))
    ).expanduser()
    publish_dir = Path(
        os.environ.get("PPTX_PUBLISH_DIR", str(default_materials_root / "slides"))
    ).expanduser()
    recursive = os.environ.get("PPTX_RECURSIVE", "0").strip() in {"1", "true", "yes"}
    cooldown_raw = os.environ.get("PPTX_POST_EXPORT_COOLDOWN_SECONDS", str(DEFAULT_POST_EXPORT_COOLDOWN_SECONDS))
    post_export_cooldown = max(DEFAULT_POST_EXPORT_COOLDOWN_SECONDS, float(cooldown_raw))
    failure_retry_raw = os.environ.get("PPTX_FAILURE_RETRY_SECONDS", str(DEFAULT_FAILURE_RETRY_SECONDS))
    failure_retry_seconds = max(5.0, float(failure_retry_raw))
    catalog_file_str = os.environ.get(
        "PPTX_CATALOG_FILE",
        str(Path(__file__).parent / "daemon" / "materials_slides_catalog.json"),
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
        post_export_cooldown_seconds=post_export_cooldown,
        failure_retry_seconds=failure_retry_seconds,
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


def list_pptx_files(folder: Path, recursive: bool) -> list[Path]:
    pattern_iter = folder.rglob("*") if recursive else folder.iterdir()
    files = [
        p for p in pattern_iter
        if p.is_file() and p.suffix.lower() == ".pptx" and not p.name.startswith("~$")
    ]
    files.sort(key=lambda p: p.name.lower())
    return files


def load_catalog_entries(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("decks", raw if isinstance(raw, list) else [])
    if not isinstance(entries, list):
        raise RuntimeError(f"Invalid slides catalog format in {path}")

    valid_entries: list[dict] = []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        source = Path(str(entry.get("source", "")).strip()).expanduser()
        if not source.exists() or not source.is_file():
            print(f"[pptx-daemon] WARN: Missing source in catalog #{idx + 1}: {source}", file=sys.stderr, flush=True)
            continue
        target_pdf = str(entry.get("target_pdf", "")).strip()
        if not target_pdf:
            target_pdf = f"{source.stem}.pdf"
        if target_pdf.lower().endswith(".pdf") is False:
            target_pdf += ".pdf"
        target_pdf = target_pdf.replace("/", "-").replace("\\", "-")
        valid_entries.append({
            "title": str(entry.get("title", "")).strip(),
            "source": source,
            "target_pdf": target_pdf,
        })
    return valid_entries


def resolve_tracked_sources(config: SlidesDaemonConfig) -> tuple[list[Path], dict[str, dict]]:
    catalog = load_catalog_entries(config.catalog_file)
    if catalog:
        paths = [entry["source"] for entry in catalog]
        meta = {
            _abs_key(entry["source"]): {
                "title": entry["title"],
                "target_pdf": entry["target_pdf"],
            }
            for entry in catalog
        }
        return paths, meta

    if config.watch_dir is None:
        return [], {}
    return list_pptx_files(config.watch_dir, recursive=config.recursive), {}


def _abs_key(path: Path) -> str:
    return str(path.expanduser().resolve())


def _lastmodified_marker_path(publish_dir: Path, target_pdf: str) -> Path:
    return publish_dir / f"{target_pdf}.lastmodified"


def read_material_last_modified(publish_dir: Path | None, target_pdf: str | None) -> float:
    if publish_dir is None or not target_pdf:
        return 0.0
    path = _lastmodified_marker_path(publish_dir, target_pdf)
    if not path.exists():
        return 0.0
    try:
        return float(path.read_text(encoding="utf-8").strip())
    except Exception:
        return 0.0


def write_material_last_modified(publish_dir: Path | None, target_pdf: str | None, source_mtime: float) -> None:
    if publish_dir is None or not target_pdf:
        return
    publish_dir.mkdir(parents=True, exist_ok=True)
    path = _lastmodified_marker_path(publish_dir, target_pdf)
    path.write_text(f"{source_mtime!r}\n", encoding="utf-8")

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SOFFICE_STDOUT_PDF_RE = re.compile(r"->\s*(.+?\.pdf)\s+using filter", re.IGNORECASE)


def list_pdf_files(folder: Path, recursive: bool) -> list[Path]:
    pattern_iter = folder.rglob("*") if recursive else folder.iterdir()
    files = [
        p for p in pattern_iter
        if p.is_file() and p.suffix.lower() == ".pdf"
    ]
    files.sort(key=lambda p: p.name.lower())
    return files


def _iso_utc(mtime: float | int | None) -> str | None:
    if mtime is None:
        return None
    try:
        return datetime.fromtimestamp(float(mtime), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "slide"


def _slide_url(config: SlidesDaemonConfig, file_name: str) -> str:
    return f"{config.public_base_url}/{urllib.parse.quote(file_name)}"


def _slides_from_publish_dir(config: SlidesDaemonConfig) -> list[dict]:
    if not config.publish_dir.exists() or not config.publish_dir.is_dir() or not config.public_base_url:
        return []
    slides: list[dict] = []
    for idx, pdf in enumerate(list_pdf_files(config.publish_dir, recursive=False)):
        base_slug = _slugify(pdf.stem)
        slug = f"{base_slug}-{idx+1}" if idx > 0 else base_slug
        slides.append({
            "name": pdf.stem,
            "slug": slug,
            "url": _slide_url(config, pdf.name),
            "updated_at": _iso_utc(pdf.stat().st_mtime),
        })
    return slides


def _slides_from_state(config: SlidesDaemonConfig, daemon_state: dict, metadata: dict[str, dict]) -> list[dict]:
    slides: list[dict] = []
    tracked = daemon_state.get("files", {})
    for key, entry in tracked.items():
        if not isinstance(entry, dict):
            continue
        source = Path(key)
        slug = str(entry.get("slug") or "").strip()
        target_pdf = str(entry.get("target_pdf") or "").strip()
        if not target_pdf:
            if not slug:
                continue
            target_pdf = f"{slug}.pdf"
        if not config.public_base_url:
            continue
        source_meta = metadata.get(key, {})
        slide_name = str(source_meta.get("title") or source.stem).strip() or source.stem
        slides.append({
            "name": slide_name,
            "slug": slug or _slugify(slide_name),
            "url": _slide_url(config, target_pdf),
            "updated_at": _iso_utc(entry.get("last_exported_mtime")),
        })
    slides.sort(key=lambda item: str(item["name"]).lower())
    return slides


def _merge_slides(primary: list[dict], secondary: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen_urls: set[str] = set()
    for source in (primary, secondary):
        for slide in source:
            name = str(slide.get("name") or "").strip()
            url = str(slide.get("url") or "").strip()
            if not name or not url or url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append({
                "name": name,
                "slug": str(slide.get("slug") or _slugify(name)).strip() or _slugify(name),
                "url": url,
                "updated_at": slide.get("updated_at"),
            })
    return merged


def detect_changed_files(
    files: list[Path],
    daemon_state: dict,
    metadata: dict[str, dict] | None = None,
    publish_dir: Path | None = None,
) -> list[Path]:
    changed: list[tuple[float, Path]] = []
    tracked = daemon_state.setdefault("files", {})
    metadata = metadata or {}
    for pptx in files:
        key = _abs_key(pptx)
        exported_mtime = float(tracked.get(key, {}).get("last_exported_mtime", 0))
        current_mtime = pptx.stat().st_mtime
        target_pdf = metadata.get(key, {}).get("target_pdf")
        marker_mtime = read_material_last_modified(publish_dir, target_pdf)
        known_mtime = max(exported_mtime, marker_mtime)
        if current_mtime > known_mtime + 1e-9:
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
    soffice_override = os.environ.get("PPTX_SOFFICE_BIN", "").strip()
    soffice_candidates = []
    if soffice_override:
        soffice_candidates.append(soffice_override)
    soffice_candidates.extend(
        [
            "soffice",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            str(Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice"),
        ]
    )

    soffice_cmd: str | None = None
    for candidate in soffice_candidates:
        if not candidate:
            continue
        if os.path.isabs(candidate):
            if os.path.exists(candidate):
                soffice_cmd = candidate
                break
            continue
        resolved = shutil.which(candidate)
        if resolved:
            soffice_cmd = resolved
            break

    if soffice_cmd is None:
        raise RuntimeError(
            "LibreOffice conversion failed: 'soffice' not found. "
            "Install LibreOffice or set PPTX_SOFFICE_BIN."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        soffice_cmd,
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(pptx_path),
    ]
    started_at = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"LibreOffice conversion failed: {proc.stderr.strip() or proc.stdout.strip()}")
    stderr_text = (proc.stderr or "").strip()
    if "source file could not be loaded" in stderr_text.lower():
        raise RuntimeError(f"LibreOffice conversion failed: {stderr_text}")
    pdf_path = output_dir / f"{pptx_path.stem}.pdf"
    if not pdf_path.exists():
        # LibreOffice can sometimes write a different output filename than input stem.
        stdout = proc.stdout or ""
        m = _SOFFICE_STDOUT_PDF_RE.search(stdout)
        if m:
            candidate = Path(m.group(1).strip())
            if not candidate.is_absolute():
                candidate = output_dir / candidate.name
            if candidate.exists():
                return candidate

        recent_pdfs = sorted(
            [
                p for p in output_dir.glob("*.pdf")
                if p.is_file() and p.stat().st_mtime >= started_at - 1.0
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if recent_pdfs:
            return recent_pdfs[0]
        raise RuntimeError(
            f"Expected PDF not found: {pdf_path}. "
            f"LibreOffice stdout: {(proc.stdout or '').strip()}"
        )
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


def upload_pdf(pdf_path: Path, slug: str, config: SlidesDaemonConfig, target_name: str | None = None) -> str:
    target_name = target_name or f"{slug}.pdf"

    if config.upload_mode == "copy":
        config.publish_dir.mkdir(parents=True, exist_ok=True)
        target_path = config.publish_dir / target_name
        shutil.copy2(pdf_path, target_path)
        if config.public_base_url:
            return f"{config.public_base_url}/{target_name}"
        return str(target_path)

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
        return f"{config.public_base_url}/{target_name}" if config.public_base_url else remote_target

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
            with urllib.request.urlopen(req, timeout=30, context=_ssl_context()):
                pass
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP PUT upload failed with status {exc.code}") from exc
        return f"{config.public_base_url}/{target_name}" if config.public_base_url else upload_url

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


def push_slides_list(config: SlidesDaemonConfig, slides: list[dict]) -> None:
    payload = {
        "status": "ready",
        "message": "Agent ready.",
        "slides": slides,
    }
    _post_json(
        f"{config.server_url}/api/quiz-status",
        payload,
        config.host_username,
        config.host_password,
    )


def sync_slides_list(config: SlidesDaemonConfig, daemon_state: dict, metadata: dict[str, dict]) -> bool:
    if not config.sync_backend:
        return False
    slides = _merge_slides(
        _slides_from_publish_dir(config),
        _slides_from_state(config, daemon_state, metadata),
    )
    payload_hash = hashlib.sha256(json.dumps(slides, sort_keys=True).encode("utf-8")).hexdigest()
    if payload_hash == daemon_state.get("last_slides_hash"):
        return False
    push_slides_list(config, slides)
    daemon_state["last_slides_hash"] = payload_hash
    save_daemon_state(config.state_file, daemon_state)
    print(f"[pptx-daemon] Published slides list ({len(slides)} entries)", flush=True)
    return True


def process_one_file(
    config: SlidesDaemonConfig,
    daemon_state: dict,
    pptx_path: Path,
    target_pdf: str | None = None,
) -> bool:
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
    public_ref = upload_pdf(pdf_path, slug, config, target_name=target_pdf)
    if config.sync_backend:
        push_current_slides(config, public_ref, slug, pptx_path.name)

    key = _abs_key(pptx_path)
    daemon_state.setdefault("files", {}).setdefault(key, {})
    daemon_state["files"][key]["slug"] = slug
    if target_pdf:
        daemon_state["files"][key]["target_pdf"] = target_pdf
    source_mtime = pptx_path.stat().st_mtime
    daemon_state["files"][key]["last_exported_mtime"] = source_mtime
    save_daemon_state(config.state_file, daemon_state)
    write_material_last_modified(config.publish_dir, target_pdf, source_mtime)
    print(f"[pptx-daemon] Published {pptx_path.name} -> {public_ref}", flush=True)
    return True


def run_once(config: SlidesDaemonConfig, daemon_state: dict) -> bool:
    files, metadata = resolve_tracked_sources(config)
    changed = detect_changed_files(files, daemon_state, metadata=metadata, publish_dir=config.publish_dir)
    updated_current = False
    if changed:
        cooldown = max(DEFAULT_POST_EXPORT_COOLDOWN_SECONDS, float(config.post_export_cooldown_seconds))
        last_finished_at = float(daemon_state.get("last_export_finished_at", 0.0))
        now_epoch = time.time()
        next_allowed_at = last_finished_at + cooldown
        if now_epoch < next_allowed_at:
            wait_s = next_allowed_at - now_epoch
            print(
                f"[pptx-daemon] Cooldown active ({wait_s:.1f}s remaining) -- delaying next export",
                flush=True,
            )
        else:
            # serialize: process one file per poll cycle
            next_path = changed[0]
            next_key = _abs_key(next_path)
            failed_until = float(daemon_state.setdefault("files", {}).get(next_key, {}).get("retry_after", 0.0))
            if now_epoch < failed_until:
                wait_s = failed_until - now_epoch
                print(
                    f"[pptx-daemon] Retry backoff active for {next_path.name} ({wait_s:.1f}s remaining)",
                    flush=True,
                )
                updated_list = sync_slides_list(config, daemon_state, metadata)
                return updated_current or updated_list
            print(f"✏️ppt update detected => regenerating ppf: {next_path.name}", flush=True)
            target_pdf = metadata.get(_abs_key(next_path), {}).get("target_pdf")
            try:
                updated_current = process_one_file(config, daemon_state, next_path, target_pdf=target_pdf)
                if updated_current:
                    daemon_state["last_export_finished_at"] = time.time()
                    daemon_state.setdefault("files", {}).setdefault(next_key, {}).pop("retry_after", None)
                    save_daemon_state(config.state_file, daemon_state)
            except Exception:
                retry_after = time.time() + max(5.0, float(config.failure_retry_seconds))
                daemon_state.setdefault("files", {}).setdefault(next_key, {})["retry_after"] = retry_after
                save_daemon_state(config.state_file, daemon_state)
                raise
    updated_list = sync_slides_list(config, daemon_state, metadata)
    return updated_current or updated_list


def run_forever(config: SlidesDaemonConfig) -> None:
    daemon_state = load_daemon_state(config.state_file)
    source_desc = f"catalog={config.catalog_file}" if config.catalog_file and config.catalog_file.exists() else f"watch={config.watch_dir}"
    print(
        f"[pptx-daemon] Watching {source_desc} every {config.poll_interval_seconds:.0f}s "
        f"(converter={config.converter}, upload={config.upload_mode}, publish={config.publish_dir})",
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
