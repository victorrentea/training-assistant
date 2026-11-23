"""SlidesRunner — initializes slide catalog from disk for the main daemon."""

import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from daemon import log
from daemon.misc.state import misc_state
from daemon.session.state import get_active_session_id
from daemon.slides import daemon as slides_daemon
from daemon.slides import save_origin
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



def _run_redownload_poller(slug: str, drive_export_url: str, source: Path | None = None,
                           hold_back: Callable[[], None] | None = None) -> None:
    """Background thread: call Railway REST to re-download PDF, compare hashes, retry if unchanged.

    On success (hash changed): marks cached, broadcasts refreshed_slugs.
    On exhaustion (hash unchanged after retries): logs warning, beeps.

    `hold_back`: this is the print of an auto-save, which must not come up under the
    trainer's hands. If he is back in PowerPoint by the time it would start, nothing is
    printed or downloaded and `hold_back` puts the deck back among the waiting ones.
    """
    from daemon.slides.router import (
        _mark_cache_status,
        download_on_railway,
    )

    prev_hash = misc_state.slides_updated.get(slug, {}).get("last_sha256", "")

    try:
        # The deck open in PowerPoint: its changed slides are printed there and sent, as
        # PowerPoint draws them. Google's conversion below is the fallback (deck not open,
        # a slide show running, no printer) — see daemon/slides/local_publish.py.
        if source is not None:
            from daemon.slides import local_publish
            outcome = local_publish.attempt(slug, source, upload=True, in_front_ok=hold_back is None)
            if outcome == "done":
                _mark_cache_status(slug, "cached")
                return
            if hold_back is not None and outcome == "not_now" and save_origin.powerpoint_frontmost():
                hold_back()
                return
        log.info("slides", f"Waiting {_REDOWNLOAD_FIRST_DELAY_S:.0f}s for Google Drive to sync before polling slug={slug}")
        time.sleep(_REDOWNLOAD_FIRST_DELAY_S)
        for attempt in range(1, _REDOWNLOAD_MAX_RETRIES + 1):
            try:
                result = download_on_railway(slug, drive_export_url)
                new_hash = result.get("sha256", "")

                if new_hash != prev_hash:
                    log.info("slides", f"Google Drive PDF updated for slug={slug} (attempt {attempt})")
                    _mark_cache_status(slug, "cached", last_sha256=new_hash)
                    # Broadcast happens in ws_client when slide_log "download_slide_completed" arrives
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
        from daemon.slides.router import _finish_download, _trigger_pending_redownload
        if _finish_download(slug):
            _trigger_pending_redownload(slug)


class SlidesRunner:
    """Initialize slide catalog and cache status at daemon startup."""

    def __init__(self, main_config):
        self.main_config = main_config
        self._slides_config: SlidesDaemonConfig | None = None
        self._slides_state: dict = {}
        # slug → deck: saved by Victor Mac with PowerPoint in front; printed once it is not.
        self._deferred_prints: dict[str, Path] = {}

    def start(self) -> None:
        from daemon.slides import pdf_printer
        pdf_printer.recover()
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
        from daemon.slides import seen_slides
        seen_slides.set_catalog_resolver(self.catalog_slug)
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

    def catalog_slug(self, source: Path) -> str | None:
        """The slides-catalog slug of a deck file, if it is one of the catalog's decks."""
        slug = (self._slides_state.get("files", {}).get(_abs_key(source)) or {}).get("slug")
        return slug if slug and slug in misc_state.slides_catalog else None

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
        self._release_deferred_prints()
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
            # Skip orphan slugs (in state file but no longer in catalog) — they have no
            # status field in misc_state.slides_updated, which would break DecksUpdatedMsg.
            if slug not in misc_state.slides_catalog:
                continue
            pptx_mtime = entry.get("pptx_mtime")
            if pptx_mtime is None:
                continue
            existing = misc_state.slides_updated.get(slug, {})
            iso = _iso_utc(pptx_mtime)
            if existing.get("modified_at") != iso:
                misc_state.slides_updated[slug] = {**existing, "modified_at": iso}
                # Proactively verify Google can still export this (changed) deck
                # to PDF and alarm the macOS add-on if it keeps failing — runs
                # for every changed deck, even if no participant requests it.
                catalog_entry = misc_state.slides_catalog.get(slug, {})
                drive_url = catalog_entry.get("drive_export_url", "")
                if drive_url:
                    from daemon.slides.export_probe import schedule_probe
                    # Notification shows the pptx filename (source_name), falling
                    # back to the catalog title, then the slug.
                    deck_name = catalog_entry.get("source_name") or catalog_entry.get("title") or slug
                    schedule_probe(slug, deck_name, drive_url)
                if existing.get("status") == "cached":
                    drive_url = misc_state.slides_catalog.get(slug, {}).get("drive_export_url", "")
                    if drive_url:
                        # Victor Mac saved it, not Victor: PowerPoint's print progress bar
                        # waits until he has left PowerPoint (see save_origin.py).
                        if save_origin.defer_print(Path(_key), float(pptx_mtime)):
                            if slug not in self._deferred_prints:
                                log.info("slides", f"PPTX auto-saved for slug={slug} — print waits for PowerPoint to leave the front")
                            self._deferred_prints[slug] = Path(_key)
                            continue
                        self._deferred_prints.pop(slug, None)
                        self._start_redownload(slug, drive_url, Path(_key))
        return True

    def _hold_back(self, slug: str, source: Path) -> None:
        """Called on the poller thread: he came back to PowerPoint before the print of an
        auto-save could start. The deck waits again, and shows as cached as it was."""
        from daemon.slides.router import _broadcast_slides_updated, _mark_cache_status
        log.info("slides", f"PowerPoint is in front again — the print of the auto-saved slug={slug} waits")
        self._deferred_prints.setdefault(slug, source)
        _mark_cache_status(slug, "cached")
        _broadcast_slides_updated()

    def _start_redownload(self, slug: str, drive_url: str, source: Path, behind_only: bool = False) -> bool:
        """`behind_only`: the print of an auto-save, never started with PowerPoint in front."""
        from daemon.slides.router import (
            _broadcast_slides_updated,
            _claim_download,
            _mark_cache_status,
            _queue_pending_redownload,
        )
        if not _claim_download(slug):
            log.info("slides", f"PPTX updated for slug={slug} — queuing redownload after current completes")
            _queue_pending_redownload(slug)
            return False
        log.info("slides", f"PPTX updated for slug={slug} — starting redownload poller")
        _mark_cache_status(slug, "downloading")
        _broadcast_slides_updated()
        threading.Thread(
            target=_run_redownload_poller,
            args=(slug, drive_url, source, (lambda: self._hold_back(slug, source)) if behind_only else None),
            daemon=True,
            name=f"redownload-{slug}",
        ).start()
        return True

    def _release_deferred_prints(self) -> None:
        """Prints held back after an auto-save go out once PowerPoint is not in front."""
        if not self._deferred_prints or save_origin.powerpoint_frontmost():
            return
        from daemon.slides.router import _claim_download, _finish_download
        for slug, source in list(self._deferred_prints.items()):
            drive_url = misc_state.slides_catalog.get(slug, {}).get("drive_export_url", "")
            if not drive_url:
                self._deferred_prints.pop(slug)
                continue
            # Another download in flight: try again at the next scan, with this deck as the source.
            if not _claim_download(slug):
                continue
            _finish_download(slug)
            log.info("slides", f"PowerPoint left the front — printing the auto-saved slug={slug}")
            self._deferred_prints.pop(slug)
            self._start_redownload(slug, drive_url, source, behind_only=True)
