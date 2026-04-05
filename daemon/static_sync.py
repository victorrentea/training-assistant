"""Static file sync — compare local static/ with backend inventory and upload changes."""
import base64
import hashlib
from pathlib import Path

from daemon import log
from daemon.http import _post_json

_EXCLUDED = {"version.js", "deploy-info.json", "work-hours.js"}


def compute_local_hashes(static_dir: Path) -> dict[str, str]:
    """Build {relative_path: md5_hex} for all files in a static directory (recursive)."""
    hashes = {}
    if static_dir.is_dir():
        for f in static_dir.rglob("*"):
            if f.is_file() and f.name not in _EXCLUDED:
                rel = str(f.relative_to(static_dir))
                md5 = hashlib.md5(f.read_bytes()).hexdigest()
                hashes[rel] = md5
    return hashes


def diff_hashes(local: dict[str, str], remote: dict[str, str]) -> tuple[list[str], list[str]]:
    """Compare local and remote hashes.
    Returns: (to_upload, to_delete)
    """
    to_upload = [name for name, h in local.items() if name not in remote or remote[name] != h]
    to_delete = [name for name in remote if name not in local]
    return to_upload, to_delete


def sync_static_files(
    static_dir: Path,
    remote_hashes: dict[str, str],
    server_url: str,
    username: str,
    password: str,
) -> list[str]:
    """Sync local static/ to backend. Returns successfully changed file paths."""
    local_hashes = compute_local_hashes(static_dir)
    to_upload, to_delete = diff_hashes(local_hashes, remote_hashes)

    if not to_upload and not to_delete:
        log.info("static-sync", "Static files in sync — no changes")
        return []

    changed_files: list[str] = []
    for name in to_upload:
        filepath = static_dir / name
        if not filepath.exists():
            continue
        content_b64 = base64.b64encode(filepath.read_bytes()).decode()
        try:
            _post_json(
                f"{server_url}/internal/upload-static",
                {"path": name, "content_b64": content_b64},
                username, password,
            )
            log.info("static-sync", f"↑ Uploaded: {name} ({filepath.stat().st_size // 1024} kb)")
            changed_files.append(name)
        except RuntimeError as e:
            log.error("static-sync", f"Failed to upload {name}: {e}")

    for name in to_delete:
        try:
            _post_json(
                f"{server_url}/internal/delete-static",
                {"path": name},
                username, password,
            )
            log.info("static-sync", f"Deleted remote: {name}")
            changed_files.append(name)
        except RuntimeError as e:
            log.error("static-sync", f"Failed to delete {name}: {e}")

    return changed_files
