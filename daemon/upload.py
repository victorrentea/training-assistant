"""File download handler: processes file_ready_for_download from Railway."""
import base64
import os
import ssl
import threading
import urllib.request
from pathlib import Path

from daemon import log
from daemon.http import _post_json, session_api_url
from daemon.misc.state import misc_state
from daemon.ws_messages import FileUploadedMsg
from daemon.ws_publish import host_event, send_to_railway

_HTTP_TIMEOUT = 60  # seconds, file downloads can be large


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _do_download(server_url: str, username: str, password: str,
                 session_id: str, file_id, participant_uuid: str, filename: str, size: int, session_folder: Path):
    """Download file from Railway and call ack. Runs in a background thread."""
    uploads_dir = session_folder / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    dest = uploads_dir / filename
    if dest.exists():
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        i = 1
        while dest.exists():
            dest = uploads_dir / f"{stem}_{i}{suffix}"
            i += 1

    download_url = session_api_url(server_url, session_id, f"/upload/{file_id}")
    auth = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    req = urllib.request.Request(download_url, headers={"Authorization": auth})

    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT, context=_ssl_context()) as resp:
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
    except Exception as e:
        log.error("upload", f"Download failed for {filename}: {e}")
        dest.unlink(missing_ok=True)
        return

    disk_path = str(dest.resolve())
    log.info("upload", f"Saved {filename} → {disk_path}")
    misc_state.add_uploaded_file(
        participant_uuid,
        file_id=str(file_id),
        filename=filename,
        size=int(size),
        disk_path=disk_path,
    )

    try:
        send_to_railway(
            host_event(
                FileUploadedMsg(
                    uuid=participant_uuid,
                    id=str(file_id),
                    filename=filename,
                    size=int(size),
                    disk_path=disk_path,
                )
            )
        )
    except Exception as e:
        log.error("upload", f"Failed to notify host for {filename}: {e}")

    ack_url = session_api_url(server_url, session_id, f"/upload/{file_id}/ack")
    try:
        _post_json(ack_url, {"disk_path": disk_path}, username=username, password=password)
    except Exception as e:
        log.error("upload", f"Ack failed for {filename}: {e}")


def handle_file_ready_for_download(data: dict, config):
    """Handle file_ready_for_download from Railway. Called from main thread drain_queue."""
    file_id = data.get("file_id")
    participant_uuid = str(data.get("uuid") or "")
    filename = data.get("filename", "file")
    size = int(data.get("size", 0) or 0)
    session_id = data.get("session_id") or ""

    session_folder = config.session_folder
    if session_folder is None:
        log.error("upload", f"No session folder — cannot save {filename}")
        return
    if not participant_uuid:
        log.error("upload", f"Missing participant uuid for upload {file_id}")
        return

    threading.Thread(
        target=_do_download,
        args=(config.server_url, os.environ.get("HOST_USERNAME", "host"),
              os.environ.get("HOST_PASSWORD", ""), session_id, file_id, participant_uuid,
              filename, size, session_folder),
        daemon=True,
    ).start()
