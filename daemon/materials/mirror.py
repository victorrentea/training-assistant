"""MaterialsMirrorRunner — mirrors local MATERIALS_FOLDER to backend via host-auth HTTP."""

import base64
import json
import os
import ssl
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from daemon import log
from daemon.http import _post_json
from daemon.session_state import resolve_materials_folder


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def post_material_upsert_file(
    main_config,
    relative_path: str,
    file_path: Path,
    source_mtime: float | None = None,
) -> None:
    file_bytes = file_path.read_bytes()
    boundary = f"----materials-sync-{uuid.uuid4().hex}"
    payload = []
    payload.append(f"--{boundary}\r\n".encode("utf-8"))
    payload.append(
        f'Content-Disposition: form-data; name="relative_path"\r\n\r\n{relative_path}\r\n'.encode("utf-8")
    )
    if source_mtime is not None:
        payload.append(f"--{boundary}\r\n".encode("utf-8"))
        payload.append(
            (
                'Content-Disposition: form-data; name="source_mtime"\r\n\r\n'
                f"{float(source_mtime):.6f}\r\n"
            ).encode("utf-8")
        )
    payload.append(f"--{boundary}\r\n".encode("utf-8"))
    payload.append(
        (
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
    )
    payload.append(file_bytes)
    payload.append(b"\r\n")
    payload.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(payload)

    token = base64.b64encode(
        f"{main_config.host_username}:{main_config.host_password}".encode("utf-8")
    ).decode("ascii")
    req = urllib.request.Request(
        f"{main_config.server_url}/api/materials/upsert",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=_ssl_context()):
            pass
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"materials upsert failed ({exc.code}): {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"materials upsert failed: {exc}") from exc


class MaterialsMirrorRunner:
    """Mirror local MATERIALS_FOLDER to backend server_materials via host-auth HTTP."""

    def __init__(self, main_config):
        self.main_config = main_config
        self.enabled = False
        self.folder: Path | None = None
        self.poll_interval_seconds = 0.0
        self.error_backoff_seconds = 0.0
        self.state_file: Path | None = None
        self._next_run_at = 0.0
        self._retry_after = 0.0
        self._state: dict = {"files": {}}

    def start(self) -> None:
        enabled_raw = os.environ.get("MATERIALS_MIRROR_ENABLED", "1").strip().lower()
        if enabled_raw in {"0", "false", "no", "off"}:
            log.info("materials", "Materials mirror disabled by MATERIALS_MIRROR_ENABLED")
            self.enabled = False
            return

        folder = resolve_materials_folder()
        if folder is None:
            raw = os.environ.get("MATERIALS_FOLDER", "").strip() or "<auto-detect>"
            log.info("materials", f"Materials mirror disabled: folder not found (MATERIALS_FOLDER={raw})")
            self.enabled = False
            return

        poll_raw = os.environ.get("MATERIALS_MIRROR_INTERVAL_SECONDS", "5").strip()
        try:
            poll = max(1.0, float(poll_raw))
        except ValueError:
            poll = 5.0
        backoff_raw = os.environ.get("MATERIALS_MIRROR_ERROR_BACKOFF_SECONDS", "60").strip()
        try:
            backoff = max(5.0, float(backoff_raw))
        except ValueError:
            backoff = 60.0

        state_file = Path(
            os.environ.get(
                "MATERIALS_MIRROR_STATE_FILE",
                str(Path(".server-data") / "materials_mirror_state.json"),
            )
        ).expanduser()

        self.folder = folder
        self.poll_interval_seconds = poll
        self.error_backoff_seconds = backoff
        self.state_file = state_file
        self._state = self._load_state(state_file)
        self._next_run_at = time.monotonic()
        self.enabled = True
        log.info(
            "materials",
            f"Materials mirror enabled ({self.poll_interval_seconds:.0f}s, error backoff {self.error_backoff_seconds:.0f}s): {self.folder}",
        )

    def _load_state(self, path: Path) -> dict:
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

    def _save_state(self) -> None:
        if self.state_file is None:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def _list_local_files(self) -> dict[str, dict]:
        assert self.folder is not None
        entries: dict[str, dict] = {}
        for path in sorted([p for p in self.folder.rglob("*") if p.is_file()]):
            rel = path.relative_to(self.folder).as_posix()
            stat = path.stat()
            entries[rel] = {
                "path": path,
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            }
        return entries

    def _post_material_upsert(self, relative_path: str, file_path: Path, source_mtime: float | None = None) -> None:
        post_material_upsert_file(self.main_config, relative_path, file_path, source_mtime=source_mtime)

    def _post_material_delete(self, relative_path: str) -> None:
        _post_json(
            f"{self.main_config.server_url}/api/materials/delete",
            {"relative_path": relative_path},
            self.main_config.host_username,
            self.main_config.host_password,
        )

    def tick(self) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if now < self._next_run_at:
            return
        if now < self._retry_after:
            return
        try:
            local = self._list_local_files()
            tracked = self._state.setdefault("files", {})

            uploaded = 0
            deleted = 0

            for rel_path, meta in local.items():
                known = tracked.get(rel_path)
                is_changed = (
                    not isinstance(known, dict)
                    or float(known.get("mtime", -1)) != float(meta["mtime"])
                    or int(known.get("size", -1)) != int(meta["size"])
                )
                if not is_changed:
                    continue
                self._post_material_upsert(rel_path, meta["path"], source_mtime=float(meta["mtime"]))
                tracked[rel_path] = {
                    "mtime": meta["mtime"],
                    "size": meta["size"],
                }
                uploaded += 1

            removed_paths = [rel for rel in list(tracked.keys()) if rel not in local]
            for rel_path in removed_paths:
                self._post_material_delete(rel_path)
                tracked.pop(rel_path, None)
                deleted += 1

            if uploaded or deleted:
                self._save_state()
                log.info("materials", f"Synced materials: {uploaded} upsert, {deleted} delete")
        except Exception as exc:
            log.error("materials", f"Materials mirror error: {exc}")
            self._retry_after = now + self.error_backoff_seconds
        finally:
            self._next_run_at = now + self.poll_interval_seconds
