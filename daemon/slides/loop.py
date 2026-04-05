"""SlidesPollingRunner — runs PPTX change detection from inside the main daemon."""

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from daemon import log
from daemon.slides import daemon as slides_daemon
from daemon.misc.state import misc_state
from daemon.slides.catalog import (
    _abs_key,
    _slugify,
    detect_changed_files,
    ensure_slug,
    load_catalog_entries,
    resolve_tracked_sources,
)
from daemon.slides.convert import poll_fingerprint_until_changed, _fingerprints
from daemon.slides.daemon import save_daemon_state
from daemon.slides.router import get_event_loop


class SlidesPollingRunner:
    """Watch PPTX files for changes and notify the backend via WebSocket."""

    def __init__(self, main_config):
        self.main_config = main_config
        self.enabled = False
        self.poll_interval_seconds = 0.0
        self._next_run_at = 0.0
        self._slides_config = None
        self._slides_state: dict = {}
        self._bg_thread: threading.Thread | None = None
        self._send_ws_message = None  # callable(dict) → bool, injected after start()

    def set_ws_sender(self, sender) -> None:
        """Inject a callable(dict) that sends a message over the daemon WebSocket."""
        self._send_ws_message = sender

    def start(self) -> None:
        try:
            cfg = slides_daemon.config_from_env()
        except Exception as exc:
            log.info("slides", f"Slides watcher disabled: {exc}")
            self.enabled = False
            return

        # Keep one auth/server source of truth from training_daemon config.
        cfg = SimpleNamespace(**vars(cfg))
        cfg.server_url = self.main_config.server_url
        cfg.host_username = self.main_config.host_username
        cfg.host_password = self.main_config.host_password

        self._slides_config = cfg
        self._slides_state = slides_daemon.load_daemon_state(cfg.state_file)
        self.poll_interval_seconds = max(0.1, float(cfg.poll_interval_seconds))
        self._next_run_at = time.monotonic()
        self.enabled = True
        log.info("slides", f"Slides watcher enabled ({self.poll_interval_seconds:.0f}s)")
        self._init_misc_state_from_catalog(cfg)

    def _init_misc_state_from_catalog(self, cfg) -> None:
        """Populate misc_state.slides_catalog and slides_cache_status from the catalog file."""
        entries = load_catalog_entries(cfg.catalog_file)
        if not entries:
            return
        tracked = self._slides_state.get("files", {})
        catalog_entries = []
        for entry in entries:
            key = _abs_key(entry["source"])
            slug = tracked.get(key, {}).get("slug") or _slugify(Path(entry["target_pdf"]).stem)
            catalog_entries.append({
                "slug": slug,
                "title": entry["title"],
                "drive_export_url": entry["drive_export_url"],
            })
        misc_state.update_slides_catalog(catalog_entries)

        # Initialize cache status by checking on-disk PDFs
        for raw_entry, catalog_entry in zip(entries, catalog_entries):
            slug = catalog_entry["slug"]
            if slug not in misc_state.slides_cache_status:
                pdf_exists = (cfg.publish_dir / raw_entry["target_pdf"]).exists()
                misc_state.slides_cache_status[slug] = {
                    "status": "cached" if pdf_exists else "not_cached"
                }
        log.info("slides", f"Initialized catalog: {len(catalog_entries)} entries")

    def _run_once_bg(self) -> None:
        try:
            cfg = self._slides_config
            state = self._slides_state
            files, metadata = resolve_tracked_sources(cfg)
            changed = detect_changed_files(files, state, metadata=metadata, publish_dir=cfg.publish_dir)
            if not changed:
                return
            for pptx_path in changed:
                key = _abs_key(pptx_path)
                slug = ensure_slug(state, pptx_path)
                # Update the tracked mtime so we don't re-fire on next poll
                state.setdefault("files", {}).setdefault(key, {})["last_exported_mtime"] = pptx_path.stat().st_mtime
                save_daemon_state(cfg.state_file, state)
                log.info("slides", f"PPTX changed: {pptx_path.name} (slug={slug}) — sending slide_invalidated")
                if self._send_ws_message is not None:
                    sent = self._send_ws_message({"type": "slide_invalidated", "slug": slug})
                    if not sent:
                        log.error("slides", f"slide_invalidated not sent (WS not connected) for slug={slug}")
                else:
                    log.error("slides", f"slide_invalidated: no WS sender configured for slug={slug}")

                # Schedule fingerprint polling to detect when GDrive PDF changes
                drive_export_url = metadata.get(key, {}).get("drive_export_url", "").strip()
                if drive_export_url:
                    event_loop = get_event_loop()
                    if event_loop is not None:
                        baseline = _fingerprints.get(slug, "")
                        coro = poll_fingerprint_until_changed(slug, drive_export_url, baseline)
                        asyncio.run_coroutine_threadsafe(coro, event_loop)
                        log.info("slides", f"fingerprint polling scheduled for slug={slug}")
                    else:
                        log.info("slides", f"fingerprint polling skipped for slug={slug}: event loop not available yet")
                else:
                    log.info("slides", f"fingerprint polling skipped for slug={slug}: no drive_export_url in metadata")
        except Exception as exc:
            log.error("slides", f"Slides watcher error: {exc}")

    def tick(self) -> None:
        if not self.enabled:
            return
        # Don't start a new run while a previous one is still in progress.
        if self._bg_thread is not None and self._bg_thread.is_alive():
            return
        now = time.monotonic()
        if now < self._next_run_at:
            return
        self._next_run_at = now + self.poll_interval_seconds
        self._bg_thread = threading.Thread(target=self._run_once_bg, daemon=True)
        self._bg_thread.start()
