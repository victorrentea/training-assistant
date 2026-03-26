"""E2E regression: participant slides keep a visible track of visited topics."""


def _dock_item_has_class(page, title: str, token: str) -> bool:
    return bool(page.evaluate(
        """([slideTitle, classToken]) => {
            const titleEl = Array.from(document.querySelectorAll('.slides-list-title'))
              .find((el) => el.textContent.trim() === slideTitle);
            if (!titleEl) return false;
            const item = titleEl.closest('.slides-list-item');
            if (!item) return false;
            return item.classList.contains(classToken);
        }""",
        [title, token],
    ))


def test_slides_mark_visited_and_persist_across_reload(pax):
    pax.join("SlidesVisited")
    page = pax._page

    page.get_by_role("button", name="Deck-A").click()
    page.wait_for_function("""() => document.getElementById('slides-overlay')?.classList.contains('open')""")

    page.get_by_role("button", name="Deck-B").click()
    page.wait_for_function("""() => (localStorage.getItem('workshop_slide_selected_id') || '').startsWith('deck-b|')""")

    assert _dock_item_has_class(page, 'Deck-A', 'visited')
    assert _dock_item_has_class(page, 'Deck-B', 'visited')

    page.evaluate("""() => {
        localStorage.setItem('workshop_slide_page:deck-a', '4');
    }""")
    page.locator('.slides-preview-close').click()
    page.wait_for_function("""() => !document.getElementById('slides-overlay')?.classList.contains('open')""")
    page.get_by_role("button", name="Deck-A").click()
    page.wait_for_function("""() => document.getElementById('slides-overlay')?.classList.contains('open')""")
    page.wait_for_function(
        """() => {
            const frame = document.querySelector('.slides-native-frame');
            if (!frame) return true; // PDF.js mode does not use native frame
            return String(frame.getAttribute('src') || '').includes('#page=4');
        }"""
    )

    page.reload(wait_until='networkidle')
    page.wait_for_function("""() => document.querySelectorAll('.slides-list-item').length > 0""")
    assert _dock_item_has_class(page, 'Deck-A', 'visited')
    assert _dock_item_has_class(page, 'Deck-B', 'visited')
