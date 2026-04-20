"""
Catalog loading, tracked-source resolution, file listing, and slide-list helpers.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path

from daemon import log
from daemon.slides.daemon import SlidesDaemonConfig


def _abs_key(path: Path) -> str:
    return str(path.expanduser().resolve())


def _lastmodified_marker_path(publish_dir: Path, target_pdf: str) -> Path:
    return publish_dir / f"{target_pdf}.lastmodified"


def read_material_last_modified(publish_dir: Path | None, target_pdf: str | None) -> float:
    if publish_dir is None or not target_pdf:
        return 0.0
    path = _lastmodified_marker_path(publish_dir, target_pdf)
    if not path.exists():
        return 0.0
    try:
        return float(path.read_text(encoding="utf-8").strip())
    except Exception:
        return 0.0


def write_material_last_modified(publish_dir: Path | None, target_pdf: str | None, source_mtime: float) -> None:
    if publish_dir is None or not target_pdf:
        return
    publish_dir.mkdir(parents=True, exist_ok=True)
    path = _lastmodified_marker_path(publish_dir, target_pdf)
    path.write_text(f"{source_mtime!r}\n", encoding="utf-8")


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def list_pptx_files(folder: Path, recursive: bool) -> list[Path]:
    pattern_iter = folder.rglob("*") if recursive else folder.iterdir()
    files = [
        p for p in pattern_iter
        if p.is_file() and p.suffix.lower() == ".pptx" and not p.name.startswith("~$")
    ]
    files.sort(key=lambda p: p.name.lower())
    return files


def list_pdf_files(folder: Path, recursive: bool) -> list[Path]:
    pattern_iter = folder.rglob("*") if recursive else folder.iterdir()
    files = [
        p for p in pattern_iter
        if p.is_file() and p.suffix.lower() == ".pdf"
    ]
    files.sort(key=lambda p: p.name.lower())
    return files


def load_catalog_entries(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("decks", raw if isinstance(raw, list) else [])
    if not isinstance(entries, list):
        raise RuntimeError(f"Invalid slides catalog format in {path}")

    valid_entries: list[dict] = []
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        source = Path(str(entry.get("source", "")).strip()).expanduser()
        if not source.exists() or not source.is_file():
            log.error("slides", f"Missing source in catalog #{idx + 1}: {source}")
            continue
        target_pdf = str(entry.get("target_pdf", "")).strip()
        if not target_pdf:
            target_pdf = f"{source.stem}.pdf"
        if target_pdf.lower().endswith(".pdf") is False:
            target_pdf += ".pdf"
        target_pdf = target_pdf.replace("/", "-").replace("\\", "-")
        valid_entries.append({
            "title": str(entry.get("title", "")).strip(),
            "source": source,
            "target_pdf": target_pdf,
            "drive_export_url": str(entry.get("drive_export_url", "")).strip(),
            "group": str(entry.get("group", "")).strip() or None,
        })
    return valid_entries


def resolve_tracked_sources(config: SlidesDaemonConfig) -> tuple[list[Path], dict[str, dict]]:
    catalog = load_catalog_entries(config.catalog_file)
    if catalog:
        paths = [entry["source"] for entry in catalog]
        meta = {
            _abs_key(entry["source"]): {
                "title": entry["title"],
                "target_pdf": entry["target_pdf"],
                "drive_export_url": entry["drive_export_url"],
            }
            for entry in catalog
        }
        return paths, meta

    if config.watch_dir is None:
        return [], {}
    return list_pptx_files(config.watch_dir, recursive=config.recursive), {}


def _iso_utc(mtime: float | int | None) -> str | None:
    if mtime is None:
        return None
    try:
        return datetime.fromtimestamp(float(mtime), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "slide"


def _slide_url(config: SlidesDaemonConfig, file_name: str) -> str:
    return f"{config.public_base_url}/{urllib.parse.quote(file_name)}"


def _slides_from_publish_dir(config: SlidesDaemonConfig) -> list[dict]:
    if not config.publish_dir.exists() or not config.publish_dir.is_dir() or not config.public_base_url:
        return []
    slides: list[dict] = []
    for idx, pdf in enumerate(list_pdf_files(config.publish_dir, recursive=False)):
        base_slug = _slugify(pdf.stem)
        slug = f"{base_slug}-{idx+1}" if idx > 0 else base_slug
        slides.append({
            "name": pdf.stem,
            "slug": slug,
            "url": _slide_url(config, pdf.name),
            "updated_at": _iso_utc(pdf.stat().st_mtime),
        })
    return slides


def _slides_from_state(config: SlidesDaemonConfig, daemon_state: dict, metadata: dict[str, dict]) -> list[dict]:
    slides: list[dict] = []
    tracked = daemon_state.get("files", {})
    for key, entry in tracked.items():
        if not isinstance(entry, dict):
            continue
        source = Path(key)
        slug = str(entry.get("slug") or "").strip()
        target_pdf = str(entry.get("target_pdf") or "").strip()
        if not target_pdf:
            if not slug:
                continue
            target_pdf = f"{slug}.pdf"
        if not config.public_base_url:
            continue
        source_meta = metadata.get(key, {})
        slide_name = str(source_meta.get("title") or source.stem).strip() or source.stem
        slides.append({
            "name": slide_name,
            "slug": slug or _slugify(slide_name),
            "url": _slide_url(config, target_pdf),
            "updated_at": _iso_utc(entry.get("last_exported_mtime")),
            "modified_at": _iso_utc(entry.get("pptx_mtime")),
            "sync_status": "out_of_sync" if entry.get("out_of_sync") else "ok",
            "sync_message": entry.get("out_of_sync_message"),
        })
    slides.sort(key=lambda item: str(item["name"]).lower())
    return slides


def _merge_slides(primary: list[dict], secondary: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen_urls: set[str] = set()
    for source in (primary, secondary):
        for slide in source:
            name = str(slide.get("name") or "").strip()
            url = str(slide.get("url") or "").strip()
            if not name or not url or url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append({
                "name": name,
                "slug": str(slide.get("slug") or _slugify(name)).strip() or _slugify(name),
                "url": url,
                "updated_at": slide.get("updated_at"),
                "modified_at": slide.get("modified_at"),
            })
    return merged


def detect_changed_files(
    files: list[Path],
    daemon_state: dict,
    metadata: dict[str, dict] | None = None,
    publish_dir: Path | None = None,
) -> list[Path]:
    changed: list[tuple[float, Path]] = []
    tracked = daemon_state.setdefault("files", {})
    metadata = metadata or {}
    for pptx in files:
        key = _abs_key(pptx)
        entry = tracked.setdefault(key, {})
        exported_mtime = float(entry.get("last_exported_mtime", 0))
        current_mtime = pptx.stat().st_mtime
        entry["pptx_mtime"] = current_mtime
        target_pdf = metadata.get(key, {}).get("target_pdf")
        marker_mtime = read_material_last_modified(publish_dir, target_pdf)
        known_mtime = max(exported_mtime, marker_mtime)
        if current_mtime > known_mtime + 1e-9:
            changed.append((current_mtime, pptx))
    changed.sort(key=lambda x: x[0])
    return [p for _, p in changed]


def refresh_pptx_mtimes(files: list[Path], daemon_state: dict) -> bool:
    """Read st_mtime for all tracked PPTX files and update pptx_mtime in state.

    Returns True if any mtime changed.
    """
    tracked = daemon_state.setdefault("files", {})
    changed = False
    for pptx in files:
        if not pptx.exists():
            continue
        key = _abs_key(pptx)
        entry = tracked.setdefault(key, {})
        current_mtime = pptx.stat().st_mtime
        if current_mtime != entry.get("pptx_mtime"):
            entry["pptx_mtime"] = current_mtime
            changed = True
            log.info("slides", f"🖍️ PPTX Updated: {pptx.name}")
    return changed


_BARE_UUID_RE = re.compile(r"^[0-9a-f]{32}$")


def migrate_bare_uuid_slugs(daemon_state: dict) -> bool:
    """Prefix any legacy bare-UUID slugs with a human-readable stem. Returns True if anything changed."""
    migrated = False
    for key, entry in daemon_state.get("files", {}).items():
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug", "")
        if slug and _BARE_UUID_RE.match(slug):
            prefix = _slugify(Path(key).stem)
            entry["slug"] = f"{prefix}-{slug}"
            entry.pop("last_exported_mtime", None)
            migrated = True
    return migrated


def ensure_slug(daemon_state: dict, pptx_path: Path) -> str:
    key = _abs_key(pptx_path)
    tracked = daemon_state.setdefault("files", {})
    entry = tracked.setdefault(key, {})
    slug = entry.get("slug")
    if slug:
        if _BARE_UUID_RE.match(slug):
            prefix = _slugify(pptx_path.stem)
            slug = f"{prefix}-{slug}"
            entry["slug"] = slug
            entry.pop("last_exported_mtime", None)  # force re-upload under new slug
        return slug
    prefix = _slugify(pptx_path.stem)
    slug = f"{prefix}-{uuid.uuid4().hex}"
    entry["slug"] = slug
    return slug
