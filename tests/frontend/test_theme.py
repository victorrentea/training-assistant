"""The theme is decided in one place (static/theme.js), for the picker to work at all.

A `@media (prefers-color-scheme)` rule or a matchMedia on it answers the OS, not the
participant's White / Dark / Follow system choice, so it would stay out of step with
the rest of the page. Style per theme with `:where(html.dark) …` / `:where(html.light) …`.
"""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "static"
PAGES = ["participant.html", "host.html", "host-landing.html", "landing.html", "notes.html", "session-ended.html"]
SOURCES = [f for f in STATIC.glob("*") if f.suffix in {".html", ".css", ".js"} and f.name != "theme.js"]


@pytest.mark.parametrize("source", SOURCES, ids=lambda f: f.name)
def test_only_theme_js_asks_the_os(source):
    assert "prefers-color-scheme" not in source.read_text(), (
        f"{source.name}: style with :where(html.dark) / :where(html.light); the OS is theme.js's business")


@pytest.mark.parametrize("page", PAGES)
def test_theme_loads_before_any_stylesheet(page):
    html = (STATIC / page).read_text()
    theme = re.search(r'<script src="/static/theme\.js', html)
    assert theme, f"{page} must load theme.js in its <head>"
    first_css = re.search(r'<link rel="stylesheet"|<style', html)
    assert theme.start() < first_css.start(), f"{page}: theme.js must come first or the page flashes"
