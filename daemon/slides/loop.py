"""SlidesPollingRunner — runs PPTX change detection/export from inside the main daemon."""

import threading
import time

from daemon import log
from daemon.slides import daemon as slides_daemon
from daemon.slides import upload as slides_upload
from types import SimpleNamespace


class SlidesPollingRunner:
    """Run PPTX change detection/export from inside the main training daemon."""

    def __init__(self, main_config):
        self.main_config = main_config
        self.enabled = False
        self.poll_interval_seconds = 0.0
        self._next_run_at = 0.0
        self._slides_config = None
        self._slides_state: dict = {}
        self._bg_thread: threading.Thread | None = None

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
        self.poll_interval_seconds = max(1.0, float(cfg.poll_interval_seconds))
        self._next_run_at = time.monotonic()
        self.enabled = True
        log.info("slides", f"Slides watcher enabled ({self.poll_interval_seconds:.0f}s)")

    def _run_once_bg(self) -> None:
        try:
            slides_upload.run_once(self._slides_config, self._slides_state)
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
