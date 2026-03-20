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
        self._page.fill("#name-input", name)
        self._page.click("#join-btn")
        expect(self._page.locator("#main-screen")).to_be_visible(timeout=5000)

    def leave(self) -> None:
        """Click Leave; accepts confirmation dialog if it appears."""
        self._page.on("dialog", lambda d: d.accept())
        self._page.click("#leave-btn")
        expect(self._page.locator("#join-screen")).to_be_visible(timeout=5000)

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

    def expect_question_answered(self, question_id: str, timeout: int = 5000) -> None:
        expect(
            self._page.locator(f'.qa-card-p[data-id="{question_id}"]')
        ).to_have_class(lambda c: "qa-answered-p" in c, timeout=timeout)
