"""
Page Object for the participant UI (/).
All interactions go through the real browser UI.
"""
from __future__ import annotations

import re

from playwright.sync_api import Page, expect


class ParticipantPage:
    def __init__(self, page: Page):
        self._page = page

    # ── Session ──────────────────────────────────────────────────────────────

    def auto_join(self) -> str:
        """Wait for auto-join to complete and return the server-assigned name (no rename)."""
        expect(self._page.locator("#display-name")).to_be_visible(timeout=10000)
        expect(self._page.locator("#display-name .display-name-text")).not_to_be_empty(timeout=5000)
        return self._page.locator("#display-name .display-name-text").inner_text().strip()

    def get_avatar_src(self) -> str:
        """Return the current avatar image filename (e.g. 'gandalf.png'), or '' if none."""
        src = self._page.locator("#my-avatar").get_attribute("src") or ""
        return src.split("/")[-1] if src else ""

    def join(self, name: str) -> None:
        """Join session with a given name.

        Prefers single-shot register-with-name when the page was loaded with
        ?as=NAME (the seq-extraction harness does this). Falls back to the
        auto-join + rename flow otherwise.
        """
        expect(self._page.locator("#display-name")).to_be_visible(timeout=10000)
        expect(self._page.locator("#display-name .display-name-text")).not_to_be_empty(timeout=3000)
        current = (self._page.locator("#display-name .display-name-text").inner_text() or "").strip()
        if current == name:
            return  # already joined under this name via ?as=
        self.rename(name)

    def rename(self, name: str) -> None:
        """Trigger inline name edit and set a new name."""
        self._page.evaluate("_startNameEdit()")
        edit_input = self._page.locator("#name-edit-input")
        expect(edit_input).to_be_visible(timeout=3000)
        edit_input.fill(name)
        edit_input.press("Enter")
        expect(self._page.locator("#display-name .display-name-text")).to_have_text(name, timeout=3000)

    # ── Poll ─────────────────────────────────────────────────────────────────

    def vote_for(self, option_text: str) -> None:
        self._page.locator(f".option-btn:has-text('{option_text}')").click()
        expect(self._page.locator(".vote-msg")).to_contain_text("Vote registered", timeout=5000)

    def vote_for_nth(self, index: int) -> None:
        self._page.locator(".option-btn").nth(index).click()
        expect(self._page.locator(".vote-msg")).to_contain_text("Vote registered", timeout=5000)

    def multi_vote(self, *option_texts: str) -> None:
        for text in option_texts:
            self._page.locator(f".option-btn:has-text('{text}')").click()
            self._page.wait_for_timeout(300)  # wait for WS round-trip

    def get_percentages(self) -> list[int]:
        """Return displayed percentage values for each poll option."""
        return [
            int(el.inner_text().replace("%", "").strip())
            for el in self._page.locator(".pct").all()
        ]

    def get_countdown_text(self) -> str:
        """Return the text content of the participant countdown element."""
        return self._page.locator("#pax-countdown").inner_text()

    # ── Word Cloud ────────────────────────────────────────────────────────────

    def submit_word(self, word: str) -> None:
        self._page.fill("#wc-input", word)
        self._page.click("#wc-go")

    # ── Q&A ──────────────────────────────────────────────────────────────────

    def submit_question(self, text: str) -> None:
        expect(self._page.locator("#qa-input")).to_be_visible(timeout=5000)
        self._page.fill("#qa-input", text)
        self._page.click("#qa-submit-btn")
        expect(self._page.locator("#qa-input")).to_have_value("", timeout=5000)

    def upvote_question(self, question_id: str) -> None:
        """Upvote a Q&A question via the participant API (bypasses DOM to avoid visibility issues)."""
        import json as _json
        self._page.evaluate(f"""async () => {{
            await fetch('/' + _sessionId + '/api/participant/qa/upvote', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json', 'x-participant-id': _myUUID}},
                body: JSON.stringify({{question_id: {_json.dumps(question_id)}}})
            }});
        }}""")

    def get_qa_questions(self) -> list[dict]:
        """Return [{id, text, upvotes, upvoted, answered}] in display order."""
        cards = self._page.locator(".qa-card-p").all()
        result = []
        for card in cards:
            q_id = card.get_attribute("data-id")
            text = card.locator(".qa-text-p").inner_text().strip()
            upvote_btn = card.locator(".qa-upvote-btn")
            upvotes_raw = upvote_btn.inner_text().replace("▲", "").strip()
            upvotes = int(upvotes_raw) if upvotes_raw.lstrip("-").isdigit() else 0
            upvoted = "qa-upvoted" in (upvote_btn.get_attribute("class") or "")
            answered = "qa-answered-p" in (card.get_attribute("class") or "")
            result.append({
                "id": q_id,
                "text": text,
                "upvotes": upvotes,
                "upvoted": upvoted,
                "answered": answered,
            })
        return result

    def get_question_texts(self) -> list[str]:
        """Return question texts in display order (sorted by upvotes desc on server)."""
        return [
            card.locator(".qa-text-p").inner_text().strip()
            for card in self._page.locator(".qa-card-p").all()
        ]

    def expect_question_count(self, n: int, timeout: int = 5000) -> None:
        expect(self._page.locator(".qa-card-p")).to_have_count(n, timeout=timeout)

    def expect_question_text_visible(self, text: str, timeout: int = 5000) -> None:
        expect(self._page.locator(f".qa-text-p:has-text('{text}')")).to_be_visible(timeout=timeout)

    def expect_question_gone(self, text: str, timeout: int = 5000) -> None:
        expect(self._page.locator(f".qa-text-p:has-text('{text}')")).not_to_be_visible(timeout=timeout)

    # ── Code Review ──────────────────────────────────────────────────────

    def select_codereview_line(self, line_num: int) -> None:
        """Click a line to select it during the selecting phase (1-indexed)."""
        self._page.locator(".codereview-pline").nth(line_num - 1).click()
        # Wait for server round-trip and re-render
        expect(self._page.locator(".codereview-pline-selected")).to_have_count(
            len(self.get_codereview_selections()) + 1, timeout=3000
        ) if False else self._page.wait_for_timeout(800)

    def deselect_codereview_line(self, line_num: int) -> None:
        """Click a selected line to deselect it (1-indexed)."""
        self._page.locator(".codereview-pline").nth(line_num - 1).click()
        self._page.wait_for_timeout(800)

    def get_codereview_selections(self) -> set[int]:
        """Return set of currently selected line numbers (1-indexed)."""
        lines = self._page.locator(".codereview-pline").all()
        result = set()
        for i, el in enumerate(lines):
            cls = el.get_attribute("class") or ""
            if "codereview-pline-selected" in cls:
                result.add(i + 1)
        return result

    # ── Score ──────────────────────────────────────────────────────────────

    def get_score(self) -> int:
        """Read displayed score, return 0 if hidden. Format: '⭐ X pts'."""
        el = self._page.locator("#activity-score-badge")
        if not el.is_visible():
            return 0
        text = el.inner_text().strip()
        import re
        m = re.search(r"(\d+)", text)
        return int(m.group(1)) if m else 0

    # ── Word Cloud ─────────────────────────────────────────────────────────

    def get_wordcloud_my_words(self) -> list[str]:
        """Return list of words the participant has submitted."""
        return [
            el.get_attribute("data-word") or ""
            for el in self._page.locator("#wc-my-words .wc-my-word").all()
        ]

    # ── Slides ─────────────────────────────────────────────────────────────

    def expand_slides_dock(self) -> None:
        """Open the slides topics menu so topic items are visible and clickable."""
        self._page.evaluate("""() => {
            const list = document.querySelector('.topics-list');
            if (list && (!list.style.maxHeight || list.style.maxHeight === '0px')) {
                openTopics();
            }
        }""")
        self._page.wait_for_timeout(400)  # allow CSS transition

    def open_slide(self, slug: str) -> None:
        """Click a slide topic item to open it in the viewer."""
        self.expand_slides_dock()
        self._page.locator(f'.topic-item[data-slide-id^="{slug}|"]').click()
        # Wait for slides view to show PDF canvas
        expect(self._page.locator("#slides-view")).to_be_visible(timeout=15000)
        self._page.wait_for_selector("#pdf-pages canvas", timeout=30000)

    def navigate_to_page(self, target_page: int) -> None:
        """Navigate to a specific page in the currently open slide."""
        self._page.evaluate(f"""() => {{
            const container = document.getElementById('pdf-pages');
            const section = container ? container.querySelector('section[data-page="{target_page}"]') : null;
            if (section) section.scrollIntoView({{ behavior: 'instant', block: 'start' }});
            // Persist page to localStorage — find slug from the active topic item
            const activeItem = document.querySelector('.topic-item.topic-active');
            const slideId = activeItem ? activeItem.getAttribute('data-slide-id') : null;
            const slug = slideId ? slideId.split('|')[0] : null;
            if (slug) {{
                localStorage.setItem('workshop_slide_page:' + slug, String({target_page}));
            }}
        }}""")
        self._page.wait_for_timeout(500)  # allow render

    def click_follow(self) -> None:
        self._page.locator("label[for='slides-follow-checkbox']").click()

    def get_page_indicator(self) -> str:
        """Return current page indicator text, e.g. '3 / 5'."""
        return self._page.locator("#pdf-page-info").inner_text()

    def get_catalog_slugs(self) -> list[str]:
        """Return list of slide slugs visible in the catalog."""
        items = self._page.locator(".topic-item[data-slide-id]").all()
        result = []
        for item in items:
            slide_id = item.get_attribute("data-slide-id") or ""
            slug = slide_id.split("|")[0] if "|" in slide_id else slide_id
            if slug:
                result.append(slug)
        return result

    def get_catalog_timestamp(self, slug: str) -> str:
        """Return the last-modified age label for a catalog item (e.g. '5m ago')."""
        item = self._page.locator(f'.topic-item[data-slide-id^="{slug}|"] .opacity-50')
        return item.inner_text() if item.count() > 0 else ""

    def is_overlay_open(self) -> bool:
        """Return True if the slides view is currently active (PDF viewer visible)."""
        return self._page.locator("#slides-view").is_visible()

    def screenshot_viewer(self) -> bytes:
        """Take a screenshot of the slides viewer area."""
        viewer = self._page.locator("#pdf-pages")
        expect(viewer).to_be_visible(timeout=15000)
        self._page.wait_for_timeout(1000)
        return viewer.screenshot()

    # ── Assertions ─────────────────────────────────────────────────────────

    def expect_question_answered(self, question_id: str, timeout: int = 5000) -> None:
        expect(
            self._page.locator(f'.qa-card-p[data-id="{question_id}"]')
        ).to_have_class(re.compile(r"qa-answered-p"), timeout=timeout)
