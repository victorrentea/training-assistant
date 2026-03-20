"""
Page Object for the participant UI (/).
All interactions go through the real browser UI.
"""
from __future__ import annotations

from playwright.sync_api import Page, expect


class ParticipantPage:
    def __init__(self, page: Page):
        self._page = page

    # ── Session ──────────────────────────────────────────────────────────────

    def join(self, name: str) -> None:
        """Join session with a given name.
        Participants auto-join with a LotR name, so wait for main screen,
        then rename via inline edit."""
        # Wait for auto-join to complete
        expect(self._page.locator("#main-screen")).to_be_visible(timeout=10000)
        # Rename via inline edit (click on name → fill → blur)
        self._page.locator("#display-name").click()
        edit_input = self._page.locator("#name-edit-input")
        expect(edit_input).to_be_visible(timeout=3000)
        edit_input.fill(name)
        edit_input.press("Enter")
        expect(self._page.locator("#display-name")).to_have_text(name, timeout=3000)

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

    def get_percentages(self) -> list[int]:
        """Return displayed percentage values for each poll option."""
        return [
            int(el.inner_text().replace("%", "").strip())
            for el in self._page.locator(".pct").all()
        ]

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
        """Click the upvote button for a question identified by data-qid."""
        btn = self._page.locator(f'.qa-upvote-btn[data-qid="{question_id}"]')
        expect(btn).not_to_be_disabled(timeout=3000)
        btn.click()

    def get_qa_questions(self) -> list[dict]:
        """Return [{id, text, upvotes, upvoted, answered}] in display order."""
        cards = self._page.locator(".qa-card-p").all()
        result = []
        for card in cards:
            q_id = card.get_attribute("data-id")
            text = card.locator(".qa-text-p").inner_text().strip()
            upvote_btn = card.locator(".qa-upvote-btn")
            upvotes_raw = upvote_btn.inner_text()
            upvotes = int(upvotes_raw.replace("▲", "").strip())
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
        el = self._page.locator("#my-score")
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
            el.inner_text().strip()
            for el in self._page.locator("#wc-my-words .wc-my-word").all()
        ]

    # ── Assertions ─────────────────────────────────────────────────────────

    def expect_question_answered(self, question_id: str, timeout: int = 5000) -> None:
        expect(
            self._page.locator(f'.qa-card-p[data-id="{question_id}"]')
        ).to_have_class(lambda c: "qa-answered-p" in c, timeout=timeout)
