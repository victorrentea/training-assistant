import io
import json
import zipfile

from daemon.wiki import downloads


def test_frontmatter_gets_stars_and_takeaway_only_when_there_are_any():
    assert downloads.with_frontmatter("# A\n", 0, False) == "# A\n"
    assert downloads.with_frontmatter("# A\n", 2, True) == "---\nstars: 2\ntakeaway: true\n---\n# A\n"
    assert downloads.with_frontmatter("---\ntags: x\n---\n# A\n", 1, False) == "---\nstars: 1\ntags: x\n---\n# A\n"


def test_vault_zip_holds_the_notes_with_their_stars_and_skips_obsidian_settings(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / ".obsidian").mkdir(parents=True)
    (wiki / ".obsidian" / "app.json").write_text("{}")
    (wiki / "assets").mkdir()
    (wiki / "assets" / "s.png").write_bytes(b"png")
    (wiki / "Agentic loop.md").write_text("# Agentic loop\n", encoding="utf-8")
    (wiki / "Drift.md").write_text("# Drift\n", encoding="utf-8")
    payload = downloads.vault_zip(wiki, "AI@DB", {"Agentic-loop": 3}, {"Drift"})
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        assert sorted(z.namelist()) == ["AI@DB wiki/Agentic loop.md", "AI@DB wiki/Drift.md", "AI@DB wiki/assets/s.png"]
        assert z.read("AI@DB wiki/Agentic loop.md").decode().startswith("---\nstars: 3\n---\n")
        assert z.read("AI@DB wiki/Drift.md").decode().startswith("---\ntakeaway: true\n---\n")


def test_offline_site_inlines_the_bundle_in_index_and_bundles_what_the_graph_fetches(tmp_path):
    site = tmp_path / "site"
    (site / "static").mkdir(parents=True)
    (site / "downloads").mkdir()
    (site / "downloads" / "old.zip").write_bytes(b"x")
    page = '<html><head><title>t</title><script src="./postscript.js" type="module" data-persist="true"></script></head></html>'
    (site / "index.html").write_text(page)
    (site / "talks").mkdir()
    (site / "talks" / "Demo.html").write_text(page.replace("./postscript", "../postscript"))
    (site / "postscript.js").write_text("console.log('</script>')")
    (site / "static" / "contentIndex.json").write_text('{"a": 1}')
    (site / "note-badges.json").write_text("{}")
    payload = downloads.offline_site_zip(site, "T", {"Drift": 2}, {"AGENTS"})
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        names = z.namelist()
        assert "T wiki/offline.js" in names and not any("downloads/" in n for n in names)
        index = z.read("T wiki/index.html").decode()
        assert index.startswith('<html><head><script src="offline.js"></script>')
        assert "console.log('<\\/script>')" in index and 'src="./postscript.js"' not in index
        assert z.read("T wiki/talks/Demo.html").decode().count('<script src="../offline.js">') == 1
        shim = z.read("T wiki/offline.js").decode()
        assert '"static/contentIndex.json": "{\\"a\\": 1}"' in shim
        assert json.dumps({"wiki/stars": {"counts": {"Drift": 2}}, "wiki/takeaways": {"slugs": ["AGENTS"]}}) in shim
