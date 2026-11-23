"""The session's "Seen slides" deck: each slide shown once, in the form it was shown
(daemon/slides/seen_registry.py, seen_slides.py)."""
import os
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from daemon.slides import seen_registry
from daemon.slides.pptx_slides import fingerprint, slide_version
from daemon.slides.seen_registry import SeenRegistry
from daemon.slides.seen_slides import Deps, SeenSlides, SlideSeenEvent, is_seen_slug, seen_slug

# ── The rules ──


def test_a_new_slide_is_added_an_identical_reshow_changes_nothing_an_edit_updates_in_place():
    reg = SeenRegistry(session_id="s")
    assert seen_registry.record(reg, "/d/a.pptx", "a.pptx", "256", "v1", "t1") == "added"
    assert seen_registry.record(reg, "/d/a.pptx", "a.pptx", "300", "w1", "t2") == "added"
    assert seen_registry.record(reg, "/d/a.pptx", "a.pptx", "256", "v1", "t3") is None
    assert seen_registry.record(reg, "/d/a.pptx", "a.pptx", "256", "v2", "t4") == "updated"
    assert [(s.slide_id, s.version, s.first_seen) for s in reg.slides] == [("256", "v2", "t1"), ("300", "w1", "t2")]


def test_the_same_slide_id_in_another_deck_is_another_slide():
    reg = SeenRegistry(session_id="s")
    seen_registry.record(reg, "/d/a.pptx", "a.pptx", "256", "v1", "t1")
    assert seen_registry.record(reg, "/d/b.pptx", "b.pptx", "256", "v1", "t2") == "added"


def test_seen_slug_is_a_railway_safe_deck_slug():
    assert seen_slug("3zMwgs") == "seen-slides-3zmwgs"
    assert is_seen_slug(seen_slug("x")) and not is_seen_slug("agentic-engineering")


# ── The service, with PowerPoint, the printer and Railway in memory ──

PRESENTATION = '<p:presentation><p:sldIdLst>{ids}</p:sldIdLst><p:sldSz cx="12192000" cy="6858000"/></p:presentation>'


def _deck(path: Path, slides: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("ppt/presentation.xml", PRESENTATION.format(
            ids="".join(f'<p:sldId id="{sid}" r:id="r{sid}"/>' for sid in slides)))
        z.writestr("ppt/_rels/presentation.xml.rels", "<Relationships>" + "".join(
            f'<Relationship Id="r{sid}" Type="x/slide" Target="slides/slide{sid}.xml"/>' for sid in slides
        ) + "</Relationships>")
        for sid, text in slides.items():
            z.writestr(f"ppt/slides/slide{sid}.xml", f"<p:sld>{text}</p:sld>")
    return path


def _pdf(path: Path, widths: list[int]) -> Path:
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=100)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def _widths(path: Path) -> list[int]:
    return [round(float(p.mediabox.width)) for p in PdfReader(str(path)).pages]


class World:
    """One deck in PowerPoint; a "print" makes deck.pdf whose page widths say which
    slide text was printed (len(text) * 100 + position)."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.session: str | None = "sess1"
        self.frontmost = False
        self.printed: dict[str, tuple[Path, dict[str, str]]] = {}  # key → (deck.pdf, slide id → digest)
        self.prints: list[str] = []
        self.outcome = "done"  # what PowerPoint makes of a print: local_publish.PrintOutcome
        self.on_print = lambda: None
        self.uploads: list[tuple[str, list[int]]] = []
        self.broadcasts: list = []
        self.toasts: list[tuple[str, int, str]] = []
        self.catalog: dict[str, str] = {}
        self.service = SeenSlides(Deps(
            active_session=lambda: self.session,
            registry_dir=lambda sid: tmp / "session-folder",
            cache_root=tmp / "cache",
            catalog_slug=lambda path: self.catalog.get(str(path)),
            page_of=self.page_of,
            publish=self.print_deck,
            print_locally=self.print_deck,
            powerpoint_frontmost=lambda: self.frontmost,
            upload=lambda slug, pdf: self.uploads.append((slug, _widths(pdf))),
            broadcast=self.broadcasts.append,
            notify_trainer=lambda deck, slide, change: self.toasts.append((deck, slide, change)),
        ))
        (tmp / "session-folder").mkdir()

    def save(self, slides: dict[str, str]) -> Path:
        self.slides = slides
        return _deck(self.tmp / "talk.pptx", slides)

    def print_deck(self, key: str, source: Path) -> str:
        self.prints.append(key)
        self.on_print()
        if self.outcome != "done":
            return self.outcome
        fp = fingerprint(source)
        texts = list(self.slides.values())
        deck = _pdf(self.tmp / f"{key}-deck.pdf", [len(t) * 100 + i for i, t in enumerate(texts)])
        self.printed[key] = (deck, {sid: slide_version(d) for sid, d in fp.slides})
        return "done"

    def page_of(self, key: str, slide_id: str, digest: str):
        if key not in self.printed:
            return None
        deck, digests = self.printed[key]
        ids = list(digests)
        return (deck, ids.index(slide_id)) if digests.get(slide_id) == digest else None

    def show(self, slide_id: str, slide: int = 1):
        self.service.on_slide_seen(SlideSeenEvent(path=str(self.tmp / "talk.pptx"), deck="talk.pptx",
                                                  slide_id=slide_id, slide=slide))

    def seen(self) -> list[int]:
        return _widths(self.service.seen_pdf("sess1"))


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def test_slides_shown_make_a_deck_in_the_order_shown_without_repeats(world):
    world.save({"256": "a", "257": "bb", "258": "ccc"})
    world.show("258", 3)
    world.show("256", 1)
    world.show("258", 3)  # again, unchanged

    assert world.seen() == [302, 100]
    assert world.toasts == [("talk.pptx", 3, "added"), ("talk.pptx", 1, "added")]
    assert world.uploads[-1] == (seen_slug("sess1"), [302, 100])
    assert world.broadcasts[-1].count == 2 and world.broadcasts[-1].slug == "seen-slides-sess1"


def test_an_edited_slide_shown_again_replaces_its_page_in_place(world):
    world.save({"256": "a", "257": "bb"})
    world.show("256")
    world.show("257", 2)
    world.save({"256": "aaaa", "257": "bb"})  # edited, saved, printed again
    world.show("256")

    assert world.seen() == [400, 201]
    assert world.toasts[-1] == ("talk.pptx", 1, "updated")


def test_no_print_while_powerpoint_is_in_front_the_slide_waits(world):
    world.save({"256": "a"})
    world.frontmost = True
    world.show("256")

    assert world.prints == [] and not world.service.seen_pdf("sess1").exists()
    assert world.toasts == [("talk.pptx", 1, "added")]  # the toast does not wait for the page
    assert world.service.state().count == 0

    world.frontmost = False
    world.service.resolve()
    assert world.seen() == [100]


def test_a_failed_print_is_not_repeated_until_the_deck_is_saved_again(world, monkeypatch):
    """2026-11-23: decks with hidden slides were printed whole once a minute, all day."""
    monkeypatch.setattr("daemon.slides.seen_slides._PRINT_RETRY_S", 0.0)
    deck = world.save({"256": "a"})
    world.outcome = "failed"
    world.show("256")
    world.service.resolve()
    world.service.resolve()
    assert len(world.prints) == 1 and world.service.state().count == 0

    world.outcome = "done"
    world.service.resolve()
    assert len(world.prints) == 1, "still the same save: nothing new to print"

    os.utime(deck, (deck.stat().st_atime, deck.stat().st_mtime + 5))  # saved again
    world.service.resolve()
    assert len(world.prints) == 2 and world.seen() == [100]


def test_a_deck_powerpoint_cannot_print_right_now_is_asked_for_again_later(world, monkeypatch):
    world.save({"256": "a"})
    world.outcome = "not_now"  # the deck is closed, or a slide show runs
    world.show("256")
    world.service.resolve()
    assert len(world.prints) == 1, "not within the retry period"

    monkeypatch.setattr("daemon.slides.seen_slides._PRINT_RETRY_S", 0.0)
    world.outcome = "done"
    world.service.resolve()
    assert len(world.prints) == 2 and world.seen() == [100]


def test_powerpoint_back_in_front_stops_the_decks_still_to_print(world):
    world.save({"256": "a"})
    other = _deck(world.tmp / "other.pptx", {"900": "zz"})
    world.frontmost = True
    world.show("256")
    world.service.on_slide_seen(SlideSeenEvent(path=str(other), deck="other.pptx", slide_id="900", slide=1))
    world.frontmost = False
    world.on_print = lambda: setattr(world, "frontmost", True)  # he comes back during the first print

    world.service.resolve()

    assert len(world.prints) == 1


def test_an_existing_print_is_reused_without_printing_again(world):
    world.save({"256": "a", "257": "bb"})
    world.print_deck("k", world.tmp / "talk.pptx")
    world.catalog[str(world.tmp / "talk.pptx")] = "k"
    world.prints.clear()

    world.show("257", 2)

    assert world.prints == [] and world.seen() == [201]


def test_nothing_is_recorded_without_an_active_session(world):
    world.save({"256": "a"})
    world.session = None
    world.show("256")

    assert world.toasts == [] and world.prints == []


def test_the_registry_survives_a_restart(world):
    world.save({"256": "a"})
    world.show("256")
    again = SeenSlides(world.service.deps)

    assert [s.slide_id for s in again.registry("sess1").slides] == ["256"]
    assert again.state().count == 1
    assert (world.tmp / "session-folder" / "slides-seen.json").exists()


def test_a_slide_edited_again_before_its_page_was_printed_takes_the_newer_version(world):
    world.save({"256": "a"})
    world.frontmost = True
    world.show("256")
    world.save({"256": "aaa"})  # edited after leaving it, before any print
    world.frontmost = False
    world.service.resolve()  # prints the deck as it is now
    world.service.resolve()  # the shown version is gone: takes the newer page

    assert world.seen() == [300]


def test_clear_empties_the_deck(world):
    world.save({"256": "a"})
    world.show("256")
    world.service.clear()

    assert world.service.state().count == 0
    assert world.broadcasts[-1].count == 0


def test_pages_keep_their_links(world, tmp_path):
    """A page taken out of the printed deck keeps its link annotations."""
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_annotation(0, _uri_link())
    deck = tmp_path / "linked.pdf"
    with open(deck, "wb") as f:
        writer.write(f)
    world.save({"256": "a"})
    world.printed["linked"] = (deck, {s: slide_version(d) for s, d in fingerprint(tmp_path / "talk.pptx").slides})
    world.catalog[str(tmp_path / "talk.pptx")] = "linked"

    world.show("256")

    annots = PdfReader(str(world.service.seen_pdf("sess1"))).pages[0].get("/Annots")
    assert annots and annots[0].get_object()["/A"]["/URI"] == "https://victorrentea.ro"


def _uri_link():
    from pypdf.generic import (
        ArrayObject,
        DictionaryObject,
        FloatObject,
        NameObject,
        TextStringObject,
    )

    return DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Link"),
        NameObject("/Rect"): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(50), FloatObject(50)]),
        NameObject("/A"): DictionaryObject({
            NameObject("/S"): NameObject("/URI"),
            NameObject("/URI"): TextStringObject("https://victorrentea.ro"),
        }),
    })
