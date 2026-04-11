"""SlidesRunner — initializes slide catalog from disk for the main daemon."""

from pathlib import Path
from types import SimpleNamespace

from daemon import log
from daemon.misc.state import misc_state
from daemon.session.state import get_active_session_id
from daemon.slides import daemon as slides_daemon
from daemon.slides.catalog import (
    _abs_key,
    _iso_utc,
    _slugify,
    load_catalog_entries,
    refresh_pptx_mtimes,
    resolve_tracked_sources,
)
from daemon.slides.router import _is_cached_on_railway


class SlidesRunner:
    """Initialize slide catalog and cache status at daemon startup."""

    def __init__(self, main_config):
        self.main_config = main_config
        self._slides_config = None
        self._slides_state: dict = {}

    def start(self) -> None:
        try:
            cfg = slides_daemon.config_from_env()
        except Exception as exc:
            log.info("slides", f"Slides catalog disabled: {exc}")
            return

        # Keep one auth/server source of truth from training_daemon config.
        cfg = SimpleNamespace(**vars(cfg))
        cfg.server_url = self.main_config.server_url
        cfg.host_username = self.main_config.host_username
        cfg.host_password = self.main_config.host_password

        self._slides_config = cfg
        self._slides_state = slides_daemon.load_daemon_state(cfg.state_file)
        self._init_misc_state_from_catalog(cfg)

    def _init_misc_state_from_catalog(self, cfg) -> None:
        """Populate misc_state.slides_catalog from the catalog file (no Railway probing)."""
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
                "group": entry.get("group"),
            })
        misc_state.update_slides_catalog(catalog_entries)

        # Mark all slides as not_cached at startup; actual cache status
        # is probed on WS (re)connect via probe_railway_cache().
        for catalog_entry in catalog_entries:
            slug = catalog_entry["slug"]
            misc_state.slides_cache_status[slug] = {
                **misc_state.slides_cache_status.get(slug, {}),
                "status": "not_cached",
            }
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
            misc_state.slides_cache_status[slug] = {
                **misc_state.slides_cache_status.get(slug, {}),
                "status": status,
            }
        from daemon.slides.router import _broadcast_slides_cache_status
        _broadcast_slides_cache_status()
        log.info("slides", "Railway cache probe complete")

    def scan_pptx_mtimes(self) -> bool:
        """Read st_mtime for all tracked PPTX files; update misc_state.slides_cache_status.

        When a PPTX mtime changes and the slide was previously cached, the cache
        is invalidated (status → not_cached) so the next /check triggers a fresh
        download from Google Drive.

        Returns True if any modified_at changed (caller should broadcast slides_cache_status).
        Called every ~60s from the main loop.
        """
        if not self._slides_config:
            return False
        files, metadata = resolve_tracked_sources(self._slides_config)
        if not files:
            return False
        changed = refresh_pptx_mtimes(files, self._slides_state)
        if not changed:
            return False
        # Propagate updated modified_at and invalidate Railway cache for changed slides.
        tracked = self._slides_state.get("files", {})
        for _, entry in tracked.items():
            slug = str(entry.get("slug") or "").strip()
            if not slug:
                continue
            pptx_mtime = entry.get("pptx_mtime")
            if pptx_mtime is None:
                continue
            existing = misc_state.slides_cache_status.get(slug, {})
            iso = _iso_utc(pptx_mtime)
            if existing.get("modified_at") != iso:
                updates = {"modified_at": iso}
                if existing.get("status") == "cached":
                    updates["status"] = "not_cached"
                    log.info("slides", f"PPTX updated for slug={slug} — Railway cache invalidated")
                misc_state.slides_cache_status[slug] = {**existing, **updates}
        return True
