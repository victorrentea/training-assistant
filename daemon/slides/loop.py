"""SlidesRunner — initializes slide catalog from disk for the main daemon."""

from pathlib import Path
from types import SimpleNamespace

from daemon import log
from daemon.session.state import get_active_session_id
from daemon.slides import daemon as slides_daemon
from daemon.misc.state import misc_state
from daemon.slides.catalog import (
    _abs_key,
    _slugify,
    load_catalog_entries,
)
from daemon.slides.router import _is_cached_on_railway


class SlidesPollingRunner:
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
                "group": entry.get("group"),
            })
        misc_state.update_slides_catalog(catalog_entries)

        # Initialize cache status from Railway availability (source of truth), not local files.
        session_id = get_active_session_id()
        if session_id:
            log.info("slides", f"Checking Railway cache for session={session_id}")
        else:
            log.info("slides", "No session at startup — slides marked as not_cached")

        for catalog_entry in catalog_entries:
            slug = catalog_entry["slug"]
            status = "not_cached"
            if session_id:
                status = "cached" if _is_cached_on_railway(session_id, slug) else "not_cached"
            misc_state.slides_cache_status[slug] = {
                **misc_state.slides_cache_status.get(slug, {}),
                "status": status,
            }
        log.info("slides", f"Initialized catalog: {len(catalog_entries)} entries")

