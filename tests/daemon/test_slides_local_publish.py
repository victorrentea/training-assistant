"""Slides as PowerPoint prints them: which slides a save changed, the page tools, and what
is sent to Railway (daemon/slides/pptx_slides.py, pdf_pages.py, local_publish.py)."""
import io
import json
import urllib.error
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from daemon.slides import local_publish, pdf_pages
from daemon.slides.pptx_slides import as_ranges, changed_positions, fingerprint, hidden_slides

PRESENTATION = (
    '<p:presentation><p:sldIdLst>{ids}</p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/></p:presentation>'
)


def _deck(path: Path, slides: dict[str, str], *, order=None, notes="n", layout="L", picture=b"png",
          hidden=()) -> Path:
    """A .pptx with just enough in it: `slides` maps a slide id to its text."""
    order = order or list(slides)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/presentation.xml", PRESENTATION.format(
            ids="".join(f'<p:sldId id="{sid}" r:id="r{sid}"/>' for sid in order)))
        z.writestr("ppt/_rels/presentation.xml.rels", "<Relationships>" + "".join(
            f'<Relationship Id="r{sid}" Type="x/slide" Target="slides/slide{sid}.xml"/>' for sid in order
        ) + "</Relationships>")
        for sid, text in slides.items():
            root = '<p:sld xmlns:p="x" show="0">' if sid in hidden else '<p:sld xmlns:p="x">'
            z.writestr(f"ppt/slides/slide{sid}.xml", f"{root}{text}</p:sld>")
            z.writestr(f"ppt/slides/_rels/slide{sid}.xml.rels", (
                "<Relationships>"
                f'<Relationship Id="a" Type="x/notesSlide" Target="../notesSlides/notes{sid}.xml"/>'
                '<Relationship Id="b" Type="x/image" Target="../media/pic.png"/>'
                '<Relationship Id="c" Type="x/slideLayout" Target="../slideLayouts/layout1.xml"/>'
                "</Relationships>"))
            z.writestr(f"ppt/notesSlides/notes{sid}.xml", notes)
        z.writestr("ppt/media/pic.png", picture)
        z.writestr("ppt/slideLayouts/layout1.xml", layout)
    return path


def test_only_the_edited_slide_counts_as_changed(tmp_path):
    before = fingerprint(_deck(tmp_path / "a.pptx", {"256": "one", "257": "two", "258": "three"}))
    after = fingerprint(_deck(tmp_path / "b.pptx", {"256": "one", "257": "TWO", "258": "three"}))

    assert changed_positions(before, after) == [2]
    assert before.aspect == pytest.approx(16 / 9)


def test_speaker_notes_are_not_on_the_slide(tmp_path):
    before = fingerprint(_deck(tmp_path / "a.pptx", {"256": "one"}, notes="say hello"))
    after = fingerprint(_deck(tmp_path / "b.pptx", {"256": "one"}, notes="say goodbye"))

    assert changed_positions(before, after) == []


def test_a_replaced_picture_changes_the_slides_showing_it(tmp_path):
    before = fingerprint(_deck(tmp_path / "a.pptx", {"256": "one", "257": "two"}, picture=b"cat"))
    after = fingerprint(_deck(tmp_path / "b.pptx", {"256": "one", "257": "two"}, picture=b"dog"))

    assert changed_positions(before, after) == [1, 2]


@pytest.mark.parametrize("change", [
    {"slides": {"256": "one", "257": "two", "999": "new"}},              # a slide added
    {"slides": {"256": "one"}},                                           # one removed
    {"slides": {"256": "one", "257": "two"}, "order": ["257", "256"]},   # moved
    {"slides": {"256": "one", "257": "two"}, "layout": "other"},         # the layout they sit on
])
def test_the_whole_deck_is_printed_when_its_structure_changed(tmp_path, change):
    before = fingerprint(_deck(tmp_path / "a.pptx", {"256": "one", "257": "two"}))
    after = fingerprint(_deck(tmp_path / "b.pptx", **change))

    assert changed_positions(before, after) is None
    assert changed_positions(None, after) is None


def test_hidden_slides_are_found_by_position(tmp_path):
    deck = _deck(tmp_path / "a.pptx", {"256": "one", "257": "two", "258": "three"},
                 order=["258", "256", "257"], hidden={"256", "258"})

    assert hidden_slides(deck) == [1, 2]
    assert hidden_slides(_deck(tmp_path / "b.pptx", {"256": "one"})) == []


def test_neighbouring_slides_print_as_one_job():
    assert as_ranges([9, 2, 3, 4, 3]) == [(2, 4), (9, 9)]
    assert as_ranges([]) == []


def _pdf(path: Path, widths: list[int]) -> Path:
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=100)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def _widths(path: Path) -> list[int]:
    return [round(float(p.mediabox.width)) for p in PdfReader(str(path)).pages]


def test_changed_pages_take_their_place_in_the_deck(tmp_path):
    deck = _pdf(tmp_path / "deck.pdf", [101, 102, 103, 104])
    pages = _pdf(tmp_path / "pages.pdf", [902, 904])

    pdf_pages.replace_pages(deck, pages, [2, 4], tmp_path / "out.pdf")

    assert _widths(tmp_path / "out.pdf") == [101, 902, 103, 904]
    with pytest.raises(ValueError):
        pdf_pages.replace_pages(deck, pages, [2], tmp_path / "bad.pdf")
    with pytest.raises(ValueError):
        pdf_pages.replace_pages(deck, pages, [2, 9], tmp_path / "bad.pdf")


def test_crop_cuts_every_page_to_the_slide(tmp_path):
    printed = _pdf(tmp_path / "printed.pdf", [595, 595])

    assert pdf_pages.crop(printed, (18.0, 20.0, 196.0, 80.0), tmp_path / "out.pdf") == 2

    box = PdfReader(str(tmp_path / "out.pdf")).pages[1].mediabox
    assert (float(box.left), float(box.bottom), float(box.width), float(box.height)) == (18.0, 20.0, 178.0, 60.0)
    assert pdf_pages.matches_aspect((18.0, 264.5, 577.0, 578.5), 16 / 9)
    assert not pdf_pages.matches_aspect((0.0, 0.0, 595.0, 842.0), 16 / 9)


# ── What is sent to Railway ──

BOX = (0.0, 0.0, 160.0, 90.0)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """PowerPoint, the printer, Ghostscript and Railway, all in memory."""
    sent: list[tuple[str, dict, list[int]]] = []
    state = {"open": ["deck.pptx"], "slide_show": False, "printed": [], "refuse_pages": False}
    monkeypatch.setattr(local_publish, "_HOME", tmp_path / "cache")
    monkeypatch.setattr(local_publish.pdf_printer, "supported", lambda: True)
    monkeypatch.setattr(local_publish.pdf_printer, "open_decks", lambda: (state["open"], state["slide_show"]))

    def print_slides(name, ranges):
        state["printed"].append(ranges)
        spans = ranges or [(1, state["slides"])]
        files = []
        for i, (first, last) in enumerate(spans):
            files.append(_pdf(tmp_path / f"job-{len(state['printed'])}-{i}.pdf", [500 + n for n in range(first, last + 1)]))
        return files

    monkeypatch.setattr(local_publish.pdf_printer, "print_slides", print_slides)
    monkeypatch.setattr(local_publish.pdf_pages, "slide_box", lambda printed: BOX)
    monkeypatch.setattr(local_publish.pdf_pages, "compress", lambda src, out, pages: Path(out).write_bytes(Path(src).read_bytes()))

    def post(path, fields, pdf):
        if path.startswith("/api/slides/pages/") and state["refuse_pages"]:
            raise urllib.error.HTTPError(path, 409, "Conflict", {}, io.BytesIO(b""))
        sent.append((path, fields, [round(float(p.mediabox.width)) for p in PdfReader(str(pdf)).pages]))
        return {"sha256": f"sha-{len(sent)}"}

    monkeypatch.setattr(local_publish, "_post", post)
    state["sent"] = sent
    return state


def _save(tmp_path, world, slides):
    world["slides"] = len(slides)
    return _deck(tmp_path / "deck.pptx", slides)


def test_first_save_sends_the_whole_deck_then_only_what_changes(tmp_path, world):
    source = _save(tmp_path, world, {"256": "one", "257": "two", "258": "three", "259": "four"})
    assert local_publish.publish("deck", source) is True
    assert world["printed"] == [None]
    assert [path for path, _, _ in world["sent"]] == ["/api/slides/deck/deck"]

    _save(tmp_path, world, {"256": "one", "257": "two", "258": "THREE", "259": "four"})
    assert local_publish.publish("deck", source) is True
    assert world["printed"][-1] == [(3, 3)]
    path, fields, pages = world["sent"][-1]
    assert path == "/api/slides/pages/deck"
    assert fields == {"base_sha256": "sha-1", "positions": json.dumps([3])}
    assert len(pages) == 1

    assert local_publish.publish("deck", source) is True   # saved again, nothing changed
    assert len(world["sent"]) == 2 and len(world["printed"]) == 2


def test_railway_without_our_deck_gets_the_whole_of_it(tmp_path, world):
    source = _save(tmp_path, world, {"256": "one", "257": "two", "258": "three", "259": "four"})
    local_publish.publish("deck", source)
    world["refuse_pages"] = True   # it restarted, or holds Google's conversion

    _save(tmp_path, world, {"256": "ONE", "257": "two", "258": "three", "259": "four"})
    assert local_publish.publish("deck", source) is True

    path, _, pages = world["sent"][-1]
    assert path == "/api/slides/deck/deck" and len(pages) == 4
    assert world["printed"][-1] == [(1, 1)], "only the changed slide was printed again"


@pytest.mark.parametrize("situation", [{"open": []}, {"slide_show": True}])
def test_google_stays_the_fallback_when_powerpoint_cannot_print_it(tmp_path, world, situation):
    world.update(situation)
    source = _save(tmp_path, world, {"256": "one"})

    assert local_publish.publish("deck", source) is False
    assert local_publish.attempt("deck", source, upload=True) == "not_now", "worth asking again later"
    assert world["printed"] == [] and world["sent"] == []


def test_a_deck_with_hidden_slides_is_never_printed(tmp_path, world):
    """PowerPoint's print leaves hidden slides out: the pages would not line up with the
    slides, so the print was thrown away — after showing its progress bar (2026-11-23)."""
    world["slides"] = 3
    source = _deck(tmp_path / "deck.pptx", {"256": "one", "257": "two", "258": "three"}, hidden={"257"})

    assert local_publish.publish("deck", source) is False
    assert local_publish.attempt("deck", source, upload=False) == "failed", "not worth asking again for this save"
    assert world["printed"] == [] and world["sent"] == []


def test_a_print_that_goes_wrong_is_a_failure_of_that_save(tmp_path, world, monkeypatch):
    source = _save(tmp_path, world, {"256": "one"})
    monkeypatch.setattr(local_publish.pdf_pages, "matches_aspect", lambda box, aspect: False)

    assert local_publish.attempt("deck", source, upload=True) == "failed"
    assert world["sent"] == []


def test_a_failure_falls_back_and_is_tried_again_next_save(tmp_path, world, monkeypatch):
    source = _save(tmp_path, world, {"256": "one", "257": "two"})
    monkeypatch.setattr(local_publish.pdf_pages, "matches_aspect", lambda box, aspect: False)
    assert local_publish.publish("deck", source) is False

    monkeypatch.setattr(local_publish.pdf_pages, "matches_aspect", lambda box, aspect: True)
    assert local_publish.publish("deck", source) is True
