"""The wiki's two downloads, written into the built site so Railway serves them like any
other file of it (no endpoint of their own, nothing large through the trainer's Mac):

- "Download what you see": the site itself, made to open from disk. A browser refuses
  the wiki's fetches from file:// (the graph's index, the badges, each note's page) and
  refuses module scripts loaded from a file, so the copy carries offline.js, which
  answers those fetches from data bundled into it, and its index.html carries Quartz's
  bundle inline. The stars and takeaways are a snapshot of the build.
- "Download for Obsidian": the vault's markdown and assets, each note's stars and
  takeaway written into its frontmatter (Victor, 2026-10-23: they live in the session
  folder's wiki-stars.json / wiki-takeaways.json, not in the notes).
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

from daemon.wiki.stars import load_stars
from daemon.wiki.takeaways import load_takeaways

DOWNLOADS_DIR = "downloads"
SITE_ZIP = "wiki-site.zip"
VAULT_ZIP = "wiki-obsidian.zip"
OFFLINE_JS = "offline.js"

_SKIPPED = {".obsidian", ".DS_Store", "Icon", "Icon\r"}


def write_downloads(wiki_dir: Path, title: str, site_dir: Path) -> None:
    folder = wiki_dir.parent
    counts = {slug: len(pids) for slug, pids in load_stars(folder).items()}
    takeaways = set(load_takeaways(folder))
    vault = vault_zip(wiki_dir, title, counts, takeaways)
    site = offline_site_zip(site_dir, title, counts, takeaways)
    out = site_dir / DOWNLOADS_DIR
    out.mkdir(exist_ok=True)
    (out / VAULT_ZIP).write_bytes(vault)
    (out / SITE_ZIP).write_bytes(site)


def note_slug(rel: str) -> str:
    """Quartz's slug for a vault note: its path without .md, spaces as dashes."""
    return rel.removesuffix(".md").replace(" ", "-")


def vault_zip(wiki_dir: Path, title: str, counts: dict[str, int], takeaways: set[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(wiki_dir.rglob("*")):
            rel = path.relative_to(wiki_dir).as_posix()
            if not path.is_file() or _skipped(rel):
                continue
            name = f"{title} wiki/{rel}"
            if path.suffix == ".md":
                slug = note_slug(rel)
                text = path.read_text(encoding="utf-8")
                archive.writestr(name, with_frontmatter(text, counts.get(slug, 0), slug in takeaways))
            else:
                archive.write(path, name)
    return buffer.getvalue()


def _skipped(rel: str) -> bool:
    return any(part in _SKIPPED or part.startswith("~$") for part in rel.split("/"))


def with_frontmatter(text: str, stars: int, takeaway: bool) -> str:
    """The note with `stars:` and `takeaway:` in its frontmatter, when it has either."""
    fields = ([f"stars: {stars}"] if stars else []) + (["takeaway: true"] if takeaway else [])
    if not fields:
        return text
    block = "\n".join(fields)
    if text.startswith("---\n"):
        return f"---\n{block}\n{text[4:]}"
    return f"---\n{block}\n---\n{text}"


def offline_site_zip(site_dir: Path, title: str, counts: dict[str, int], takeaways: set[str]) -> bytes:
    data: dict[str, str] = {}
    for path in sorted(site_dir.rglob("*")):
        rel = path.relative_to(site_dir).as_posix()
        if path.is_file() and (path.suffix == ".html" or rel in ("static/contentIndex.json", "note-badges.json")):
            data[rel] = path.read_text(encoding="utf-8", errors="replace")
    api = {"wiki/stars": {"counts": counts}, "wiki/takeaways": {"slugs": sorted(takeaways)}}
    offline_js = OFFLINE_SHIM.replace("__FILES__", json.dumps(data)).replace("__API__", json.dumps(api))
    bundle = (site_dir / "postscript.js").read_text(encoding="utf-8")

    buffer = io.BytesIO()
    root = f"{title} wiki"
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(site_dir.rglob("*")):
            rel = path.relative_to(site_dir).as_posix()
            if not path.is_file() or rel.startswith(f"{DOWNLOADS_DIR}/"):
                continue
            if path.suffix == ".html":
                html = with_offline_script(data[rel], "../" * rel.count("/"))
                if rel == "index.html":
                    html = with_inline_bundle(html, bundle)
                archive.writestr(f"{root}/{rel}", html)
            else:
                archive.write(path, f"{root}/{rel}")
        archive.writestr(f"{root}/{OFFLINE_JS}", offline_js)
    return buffer.getvalue()


def with_offline_script(html: str, to_root: str) -> str:
    """offline.js first thing in <head>: before Quartz's inline script fetches its index."""
    return html.replace("<head>", f'<head><script src="{to_root}{OFFLINE_JS}"></script>', 1)


_BUNDLE_TAG = re.compile(r'<script src="\./postscript\.js" type="module"([^>]*)></script>')


def with_inline_bundle(html: str, bundle: str) -> str:
    """Quartz's bundle inline: a module script loaded from a file is refused, one written
    in the page is not. `</script` inside it would end the tag early."""
    safe = bundle.replace("</script", "<\\/script")
    return _BUNDLE_TAG.sub(lambda m: f'<script type="module"{m.group(1)}>{safe}</script>', html, count=1)


# Answers the wiki's fetches from the data bundled in, when opened from disk (file://).
# Keys are paths from the site's root; an address without an extension is a page.
OFFLINE_SHIM = """// Opened from disk, the wiki's own fetches are refused; this answers them from the
// files bundled below (training-assistant daemon/wiki/downloads.py).
(function () {
  if (location.protocol !== "file:") return
  var files = __FILES__
  var api = __API__
  var root = new URL(".", document.currentScript.src).href
  var realFetch = window.fetch.bind(window)
  function answer(body, type) {
    return Promise.resolve(new Response(body, { status: 200, headers: { "Content-Type": type } }))
  }
  window.fetch = function (input, init) {
    // A string, a URL or a Request
    var url = new URL(input instanceof Request ? input.url : String(input), location.href)
    for (var key in api) {
      if (url.pathname.endsWith("/" + key)) return answer(JSON.stringify(api[key]), "application/json")
    }
    if (url.href.indexOf(root) === 0) {
      var rel = decodeURIComponent(url.pathname.slice(new URL(root).pathname.length))
      var candidates = [rel, rel + ".html", rel.replace(/\\/$/, "") + "/index.html", rel === "" ? "index.html" : rel]
      for (var i = 0; i < candidates.length; i++) {
        var hit = files[candidates[i]]
        if (hit !== undefined) {
          return answer(hit, candidates[i].endsWith(".json") ? "application/json" : "text/html")
        }
      }
    }
    if (url.protocol === "file:") return Promise.resolve(new Response("", { status: 404 }))
    return realFetch(input, init)
  }
})()
"""
