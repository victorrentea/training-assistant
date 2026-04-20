"""SlidesRunner — initializes slide catalog from disk for the main daemon."""

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from daemon import log
from daemon.misc.state import misc_state
from daemon.session.state import get_active_session_id
from daemon.slides import daemon as slides_daemon
from daemon.slides.catalog import (
    _abs_key,
    _iso_utc,
    _slugify,
    load_catalog_entries,
    migrate_bare_uuid_slugs,
    refresh_pptx_mtimes,
    resolve_tracked_sources,
)
from daemon.slides.daemon import SlidesDaemonConfig
from daemon.slides.router import _is_cached_on_railway

_REDOWNLOAD_FIRST_DELAY_S = 10.0
_REDOWNLOAD_RETRY_INTERVAL_S = 5.0
_REDOWNLOAD_MAX_RETRIES = 5

_active_redownload_slugs: set[str] = set()
_pending_redownload_slugs: set[str] = set()  # PPTX changed while download was in-flight
_active_redownload_lock = threading.Lock()


def _run_redownload_poller(slug: str, drive_export_url: str) -> None:
    """Background thread: call Railway REST to re-download PDF, compare hashes, retry if unchanged.

    On success (hash changed): marks cached, broadcasts refreshed_slugs.
    On exhaustion (hash unchanged after retries): logs warning, beeps.
    """
    from daemon.slides.router import (
        _broadcast_slides_updated,
        _mark_cache_status,
        download_on_railway,
    )

    prev_hash = misc_state.slides_updated.get(slug, {}).get("last_sha256", "")

    try:
        log.info("slides", f"Waiting {_REDOWNLOAD_FIRST_DELAY_S:.0f}s for Google Drive to sync before polling slug={slug}")
        time.sleep(_REDOWNLOAD_FIRST_DELAY_S)
        for attempt in range(1, _REDOWNLOAD_MAX_RETRIES + 1):
            try:
                result = download_on_railway(slug, drive_export_url)
                new_hash = result.get("sha256", "")

                if new_hash != prev_hash:
                    log.info("slides", f"Google Drive PDF updated for slug={slug} (attempt {attempt})")
                    _mark_cache_status(slug, "cached", last_sha256=new_hash)
                    _broadcast_slides_updated(refreshed_slugs=[slug])
                    return

                log.info("slides", f"Google Drive PDF unchanged for slug={slug} (attempt {attempt}/{_REDOWNLOAD_MAX_RETRIES})")
            except Exception as exc:
                log.error("slides", f"Railway download failed for slug={slug} (attempt {attempt}): {exc}")

            if attempt < _REDOWNLOAD_MAX_RETRIES:
                time.sleep(_REDOWNLOAD_RETRY_INTERVAL_S)

        # Exhausted retries
        log.error("slides", f"Google Drive PDF not updated for slug={slug} after {_REDOWNLOAD_MAX_RETRIES} attempts")
        from daemon.slides.drive_sync import _beep_local
        _beep_local()
    finally:
        with _active_redownload_lock:
            _active_redownload_slugs.discard(slug)
            should_retry = slug in _pending_redownload_slugs
            _pending_redownload_slugs.discard(slug)

        if should_retry:
            drive_url = misc_state.slides_catalog.get(slug, {}).get("drive_export_url", "")
            if drive_url:
                log.info("slides", f"Starting queued redownload for slug={slug}")
                with _active_redownload_lock:
                    _active_redownload_slugs.add(slug)
                from daemon.slides.router import _mark_cache_status, _broadcast_slides_updated
                _mark_cache_status(slug, "downloading")
                _broadcast_slides_updated()
                t = threading.Thread(
                    target=_run_redownload_poller,
                    args=(slug, drive_url),
                    daemon=True,
                    name=f"redownload-{slug}",
                )
                t.start()


class SlidesRunner:
    """Initialize slide catalog and cache status at daemon startup."""

    def __init__(self, main_config):
        self.main_config = main_config
        self._slides_config: SlidesDaemonConfig | None = None
        self._slides_state: dict = {}

    def start(self) -> None:
        try:
            cfg = slides_daemon.config_from_env()
        except Exception as exc:
            log.info("slides", f"Slides catalog disabled: {exc}")
            return

        # Keep one auth/server source of truth from training_daemon config.
        ns = SimpleNamespace(**vars(cfg))
        ns.server_url = self.main_config.server_url
        ns.host_username = self.main_config.host_username
        ns.host_password = self.main_config.host_password
        cfg = cast(SlidesDaemonConfig, ns)

        self._slides_config = cfg
        self._slides_state = slides_daemon.load_daemon_state(cfg.state_file)
        if migrate_bare_uuid_slugs(self._slides_state):
            slides_daemon.save_daemon_state(cfg.state_file, self._slides_state)
            log.info("slides", "Migrated legacy bare-UUID slugs to human-readable prefixes")
        self._init_misc_state_from_catalog(cfg)
        # Run initial PPTX mtime scan so modified_at is available immediately
        self.scan_pptx_mtimes()

    def _init_misc_state_from_catalog(self, cfg) -> None:
        """Populate misc_state.slides_catalog from the catalog file (no Railway probing)."""
        entries = load_catalog_entries(cfg.catalog_file)
        if not entries:
            return
        tracked = self._slides_state.setdefault("files", {})
        catalog_entries = []
        for entry in entries:
            key = _abs_key(entry["source"])
            state_entry = tracked.setdefault(key, {})
            slug = state_entry.get("slug") or _slugify(Path(entry["target_pdf"]).stem)
            # Ensure slug is persisted in tracked state so scan_pptx_mtimes can propagate modified_at
            state_entry["slug"] = slug
            catalog_entries.append({
                "slug": slug,
                "title": entry["title"],
                "source_name": entry["source"].name,
                "drive_export_url": entry["drive_export_url"],
                "group": entry.get("group"),
            })
        misc_state.update_slides_catalog(catalog_entries)

        # Mark all slides as not_cached at startup; actual cache status
        # is probed on WS (re)connect via probe_railway_cache().
        # Also set modified_at from source PPTX file mtime if available.
        for entry, catalog_entry in zip(entries, catalog_entries):
            slug = catalog_entry["slug"]
            status: dict = {
                **misc_state.slides_updated.get(slug, {}),
                "status": "not_cached",
            }
            # Read mtime from the actual PPTX source file
            source = entry["source"]
            try:
                if source.exists():
                    status["modified_at"] = _iso_utc(source.stat().st_mtime)
            except OSError:
                pass
            misc_state.slides_updated[slug] = status
        log.info("slides", f"Initialized catalog: {len(catalog_entries)} entries")

    def probe_railway_cache(self) -> None:
        """Check Railway cache status for all catalog slugs via HEAD requests.

        Called on every WS (re)connect so the daemon has an accurate picture
        of what Railway currently has cached (survives Railway redeploys).
        """
        session_id = get_active_session_id()
        if not session_id:
            return
        slugs = list(misc_state.slides_catalog.keys())
        if not slugs:
            return
        log.info("slides", f"Probing Railway cache for {len(slugs)} slugs (session={session_id})")
        for slug in slugs:
            status = "cached" if _is_cached_on_railway(session_id, slug) else "not_cached"
            misc_state.slides_updated[slug] = {
                **misc_state.slides_updated.get(slug, {}),
                "status": status,
            }
        from daemon.slides.router import _broadcast_slides_updated
        _broadcast_slides_updated()
        log.info("slides", "Railway cache probe complete")

    def scan_pptx_mtimes(self) -> bool:
        """Read st_mtime for all tracked PPTX files; update misc_state.slides_updated.

        When a PPTX mtime changes and the slide was previously cached, starts
        a background poller thread that calls Railway REST to re-download the PDF,
        comparing hashes until Google Drive publishes the new version.

        Returns True if any modified_at changed (caller should broadcast slides_updated).
        Called every ~10s from the main loop.
        """
        if not self._slides_config:
            return False
        files, metadata = resolve_tracked_sources(self._slides_config)
        if not files:
            return False
        changed = refresh_pptx_mtimes(files, self._slides_state)
        if not changed:
            return False
        slides_daemon.save_daemon_state(self._slides_config.state_file, self._slides_state)
        # Propagate updated modified_at and start redownload poller for changed cached slides.
        tracked = self._slides_state.get("files", {})
        for _key, entry in tracked.items():
            slug = str(entry.get("slug") or "").strip()
            if not slug:
                continue
            pptx_mtime = entry.get("pptx_mtime")
            if pptx_mtime is None:
                continue
            existing = misc_state.slides_updated.get(slug, {})
            iso = _iso_utc(pptx_mtime)
            if existing.get("modified_at") != iso:
                misc_state.slides_updated[slug] = {**existing, "modified_at": iso}
                if existing.get("status") == "cached":
                    drive_url = misc_state.slides_catalog.get(slug, {}).get("drive_export_url", "")
                    if drive_url:
                        with _active_redownload_lock:
                            if slug in _active_redownload_slugs:
                                log.info("slides", f"PPTX updated for slug={slug} — queuing redownload after current completes")
                                _pending_redownload_slugs.add(slug)
                                continue
                            _active_redownload_slugs.add(slug)
                        log.info("slides", f"PPTX updated for slug={slug} — starting redownload poller")
                        from daemon.slides.router import (
                            _broadcast_slides_updated,
                            _mark_cache_status,
                        )
                        _mark_cache_status(slug, "downloading")
                        _broadcast_slides_updated()
                        t = threading.Thread(
                            target=_run_redownload_poller,
                            args=(slug, drive_url),
                            daemon=True,
                            name=f"redownload-{slug}",
                        )
                        t.start()
        return True
