from daemon.materials.viewed_decks import MIN_DECK_SECONDS, select_viewed_decks

CATALOG = {
    "agentic-engineering": {"title": "Agentic Engineering 🔥", "drive_export_url": "https://drive/ae"},
    "bio-victor": {"title": "About Victor", "drive_export_url": "https://drive/bio"},
    "clean-code": {"title": "Clean Code ✨", "drive_export_url": "https://drive/cc"},
}


def _viewed(slug, page, seconds):
    return {"slug": slug, "page": page, "seconds": seconds}


def test_airtime_is_summed_across_pages_and_ranked_most_viewed_first():
    viewed = [
        _viewed("clean-code", 1, 100),
        _viewed("agentic-engineering", 1, 300),
        _viewed("clean-code", 2, 100),
        _viewed("agentic-engineering", 7, 300),
    ]
    decks = select_viewed_decks(viewed, CATALOG)
    assert [d.slug for d in decks] == ["agentic-engineering", "clean-code"]


def test_accidental_flips_are_left_out():
    viewed = [_viewed("agentic-engineering", 3, 6011), _viewed("bio-victor", 1, 4)]
    decks = select_viewed_decks(viewed, CATALOG)
    assert [d.slug for d in decks] == ["agentic-engineering"]


def test_threshold_is_inclusive():
    decks = select_viewed_decks([_viewed("bio-victor", 1, MIN_DECK_SECONDS)], CATALOG)
    assert [d.slug for d in decks] == ["bio-victor"]


def test_filename_drops_emoji_like_the_published_pdf_and_carries_drive_url():
    (deck,) = select_viewed_decks([_viewed("agentic-engineering", 1, 999)], CATALOG)
    assert deck.filename == "Agentic Engineering.pdf"
    assert deck.drive_export_url == "https://drive/ae"


def test_slug_missing_from_catalog_is_skipped():
    assert select_viewed_decks([_viewed("gone-deck", 1, 999)], CATALOG) == []
