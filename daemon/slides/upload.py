"""
PDF upload, backend push, sync, per-file processing, and run loop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from daemon import log
from daemon.http import _get_json as _http_get_json, session_api_url, get_active_session_id
from daemon.slides.catalog import (
    _abs_key,
    _merge_slides,
    _slides_from_publish_dir,
    _slides_from_state,
    _slugify,
    detect_changed_files,
    ensure_slug,
    resolve_tracked_sources,
    write_material_last_modified,
)
from daemon.slides.convert import convert_pptx_to_pdf
from daemon.slides.daemon import (
    DEFAULT_POST_EXPORT_COOLDOWN_SECONDS,
    SlidesDaemonConfig,
    _post_json,
    _ssl_context,
    config_from_env,
    load_daemon_state,
    save_daemon_state,
)
from daemon.slides.drive_sync import _read_url_text, extract_drive_export_links
from daemon.slides.daemon import TITLE_ALIASES


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
    sid = get_active_session_id(config.server_url)
    _post_json(
        session_api_url(config.server_url, sid, "/slides/current"),
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
    sid = get_active_session_id(config.server_url)
    _post_json(
        session_api_url(config.server_url, sid, "/quiz-status"),
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
    log.info("slides", f"Published slides list ({len(slides)} entries)")
    return True


def process_one_file(
    config: SlidesDaemonConfig,
    daemon_state: dict,
    pptx_path: Path,
    target_pdf: str | None = None,
    metadata: dict | None = None,
) -> bool:
    key = _abs_key(pptx_path)
    state_entry = daemon_state.setdefault("files", {}).setdefault(key, {})
    slug = ensure_slug(daemon_state, pptx_path)
    pdf_path = convert_pptx_to_pdf(pptx_path, config, slug, state_entry, metadata=metadata)
    public_ref = upload_pdf(pdf_path, slug, config, target_name=target_pdf)
    if config.sync_backend:
        push_current_slides(config, public_ref, slug, pptx_path.name)

    daemon_state["files"][key]["slug"] = slug
    if target_pdf:
        daemon_state["files"][key]["target_pdf"] = target_pdf
    source_mtime = pptx_path.stat().st_mtime
    daemon_state["files"][key]["last_exported_mtime"] = source_mtime
    save_daemon_state(config.state_file, daemon_state)
    write_material_last_modified(config.publish_dir, target_pdf, source_mtime)
    log.info("slides", f"Published {pptx_path.name} -> {public_ref}")
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
            log.info("slides", f"Cooldown active ({wait_s:.1f}s remaining) -- delaying next export")
        else:
            # serialize: process one file per poll cycle
            next_path = changed[0]
            next_key = _abs_key(next_path)
            failed_until = float(daemon_state.setdefault("files", {}).get(next_key, {}).get("retry_after", 0.0))
            if now_epoch < failed_until:
                wait_s = failed_until - now_epoch
                log.info("slides", f"Retry backoff active for {next_path.name} ({wait_s:.1f}s remaining)")
                updated_list = sync_slides_list(config, daemon_state, metadata)
                return updated_current or updated_list
            log.info("slides", f"✏️ppt update detected => regenerating ppf: {next_path.name}")
            target_pdf = metadata.get(_abs_key(next_path), {}).get("target_pdf")
            file_meta = metadata.get(_abs_key(next_path), {})
            try:
                updated_current = process_one_file(
                    config,
                    daemon_state,
                    next_path,
                    target_pdf=target_pdf,
                    metadata=file_meta,
                )
                if updated_current:
                    daemon_state["last_export_finished_at"] = time.time()
                    daemon_state.setdefault("files", {}).setdefault(next_key, {}).pop("retry_after", None)
                    save_daemon_state(config.state_file, daemon_state)
            except Exception as exc:
                message = str(exc)
                if "drive_sync_timeout:" in message:
                    entry = daemon_state.setdefault("files", {}).setdefault(next_key, {})
                    entry["last_exported_mtime"] = next_path.stat().st_mtime
                    entry.pop("retry_after", None)
                    save_daemon_state(config.state_file, daemon_state)
                    log.error("slides", message)
                    updated_current = False
                    updated_list = sync_slides_list(config, daemon_state, metadata)
                    return updated_current or updated_list
                retry_after = time.time() + max(5.0, float(config.failure_retry_seconds))
                daemon_state.setdefault("files", {}).setdefault(next_key, {})["retry_after"] = retry_after
                save_daemon_state(config.state_file, daemon_state)
                raise
    updated_list = sync_slides_list(config, daemon_state, metadata)
    return updated_current or updated_list


def _display_name_for_key(key: str, metadata: dict[str, dict], daemon_state: dict) -> str:
    meta = metadata.get(key, {})
    title = str(meta.get("title") or "").strip()
    if title:
        return title
    entry = daemon_state.get("files", {}).get(key, {})
    target_pdf = str(entry.get("target_pdf") or "").strip()
    if target_pdf:
        return Path(target_pdf).stem
    return Path(key).name


def log_startup_drive_sync_status(config: SlidesDaemonConfig, daemon_state: dict) -> None:
    files, metadata = resolve_tracked_sources(config)
    changed = detect_changed_files(files, daemon_state, metadata=metadata, publish_dir=config.publish_dir)
    pending_names = [_display_name_for_key(_abs_key(path), metadata, daemon_state) for path in changed]

    out_of_sync_names: list[str] = []
    tracked = daemon_state.get("files", {})
    if isinstance(tracked, dict):
        for key, entry in tracked.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("out_of_sync"):
                out_of_sync_names.append(_display_name_for_key(str(key), metadata, daemon_state))

    if pending_names:
        log.info("slides", f"Startup pending Drive downloads ({len(pending_names)}): {', '.join(pending_names)}")
    else:
        log.info("slides", "Startup pending Drive downloads: none")

    if out_of_sync_names:
        log.info("slides", f"Startup out-of-sync decks ({len(out_of_sync_names)}): {', '.join(out_of_sync_names)}")
    else:
        log.info("slides", "Startup out-of-sync decks: none")


def bootstrap_drive_urls(catalog_path: Path, source_url: str) -> tuple[int, int]:
    raw_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    decks = raw_catalog.get("decks", raw_catalog if isinstance(raw_catalog, list) else [])
    if not isinstance(decks, list):
        raise RuntimeError(f"Invalid slides catalog format in {catalog_path}")

    page_html = _read_url_text(source_url)
    page_links = extract_drive_export_links(page_html)
    updated = 0
    missing = 0

    alias_to_page: dict[str, str] = {}
    for local_title, remote_title in TITLE_ALIASES.items():
        if remote_title in page_links:
            alias_to_page[local_title] = remote_title

    for entry in decks:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title", "")).strip()
        if not title:
            continue
        lookup_title = title if title in page_links else alias_to_page.get(title)
        export_url = page_links.get(lookup_title or "")
        if not export_url:
            missing += 1
            continue
        if str(entry.get("drive_export_url", "")).strip() != export_url:
            entry["drive_export_url"] = export_url
            updated += 1
        probe = str(entry.get("drive_probe_url", "")).strip()
        if not probe:
            entry["drive_probe_url"] = export_url
            updated += 1

    catalog_path.write_text(json.dumps(raw_catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return updated, missing


def run_forever(config: SlidesDaemonConfig) -> None:
    daemon_state = load_daemon_state(config.state_file)
    source_desc = f"catalog={config.catalog_file}" if config.catalog_file and config.catalog_file.exists() else f"watch={config.watch_dir}"
    log.info(
        "slides",
        f"Watching {source_desc} every {config.poll_interval_seconds:.0f}s "
        f"(converter={config.converter}, upload={config.upload_mode}, publish={config.publish_dir})",
    )
    log_startup_drive_sync_status(config, daemon_state)
    while True:
        try:
            run_once(config, daemon_state)
        except Exception as exc:
            log.error("slides", str(exc))
        time.sleep(config.poll_interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Watch PPTX files and publish exported PDFs.")
    parser.add_argument("--once", action="store_true", help="Run one poll cycle and exit")
    parser.add_argument(
        "--bootstrap-drive-urls",
        action="store_true",
        help="Populate drive_export_url/drive_probe_url in catalog from public slides page",
    )
    parser.add_argument(
        "--bootstrap-source-url",
        default="",
        help="Source page for bootstrap (default: PPTX_DRIVE_BOOTSTRAP_URL or built-in default)",
    )
    args = parser.parse_args(argv)

    try:
        config = config_from_env()
    except Exception as exc:
        log.error("slides", f"Config error: {exc}")
        return 1

    daemon_state = load_daemon_state(config.state_file)
    if args.bootstrap_drive_urls:
        if not config.catalog_file:
            print("[pptx-daemon] ERROR: Catalog file is required for bootstrap", file=sys.stderr, flush=True)
            return 1
        source_url = args.bootstrap_source_url.strip() or config.drive_bootstrap_url
        try:
            updated, missing = bootstrap_drive_urls(config.catalog_file, source_url)
            print(
                f"[pptx-daemon] Bootstrap done: updated={updated}, missing_titles={missing}, source={source_url}",
                flush=True,
            )
            return 0
        except Exception as exc:
            print(f"[pptx-daemon] ERROR: Bootstrap failed: {exc}", file=sys.stderr, flush=True)
            return 1

    if args.once:
        try:
            run_once(config, daemon_state)
            return 0
        except Exception as exc:
            log.error("slides", str(exc))
            return 1

    run_forever(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
