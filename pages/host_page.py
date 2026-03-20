"""
Page Object for the host control panel (/host).
All interactions go through the real browser UI.
"""
from __future__ import annotations

from playwright.sync_api import Page, expect


class HostPage:
    def __init__(self, page: Page):
        self._page = page

    # ── Poll ────────────────────────────────────────────────────────────────

    def create_poll(self, question: str, options: list[str], multi: bool = False) -> None:
        """Type a poll into the composer and launch it (poll opens automatically)."""
        composer = self._page.locator("#poll-input")
        composer.scroll_into_view_if_needed(timeout=10000)
        composer.click()
        composer.evaluate("el => { el.focus(); document.execCommand('selectAll'); }")
        self._page.keyboard.type("\n".join([question] + options))
        if multi:
            self._page.check("#multi-check")
        self._page.click("#create-btn")
        expect(self._page.locator("text=Close voting")).to_be_visible(timeout=5000)

    def expect_generate_button_label(self, label: str) -> None:
        expect(self._page.locator("#gen-quiz-btn")).to_have_text(label, timeout=3000)

    def set_quiz_topic(self, text: str) -> None:
        self._page.fill("#quiz-topic", text)

    def close_poll(self) -> None:
        self._page.click("text=Close voting")
        expect(self._page.locator("text=Re-open")).to_be_visible(timeout=5000)

    def reopen_poll(self) -> None:
        self._page.click("text=Re-open")
        expect(self._page.locator("text=Close voting")).to_be_visible(timeout=5000)

    def mark_correct(self, *option_texts: str) -> None:
        """Click result rows to mark options correct (by partial text match)."""
        for text in option_texts:
            self._page.locator(f".result-row:has-text('{text}')").click()

    # ── Word Cloud ──────────────────────────────────────────────────────────

    def open_wordcloud_tab(self) -> None:
        self._page.click("#tab-wordcloud")

    def submit_word(self, word: str) -> None:
        self._page.fill("#wc-host-input", word)
        self._page.press("#wc-host-input", "Enter")

    # ── Q&A ─────────────────────────────────────────────────────────────────

    def open_qa_tab(self) -> None:
        self._page.click("#tab-qa")
        expect(self._page.locator("#tab-content-qa")).to_be_visible(timeout=5000)
        expect(self._page.locator("#qa-list")).to_be_visible(timeout=5000)

    def get_qa_questions(self) -> list[dict]:
        """Return list of {id, text, upvotes, answered} as shown on host panel."""
        cards = self._page.locator(".qa-card").all()
        result = []
        for card in cards:
            q_id = card.get_attribute("data-id")
            text = card.locator(".qa-text").inner_text().strip()
            upvotes_raw = card.locator(".qa-upvotes").inner_text()
            upvotes = int(upvotes_raw.replace("▲", "").strip())
            answered = "qa-answered" in (card.get_attribute("class") or "")
            result.append({"id": q_id, "text": text, "upvotes": upvotes, "answered": answered})
        return result

    def edit_question(self, question_id: str, new_text: str) -> None:
        """Trigger inline edit on a Q&A card and submit via Enter."""
        import json as _json
        self._page.evaluate(f"() => editQuestion({_json.dumps(question_id)})")
        input_el = self._page.locator(f'.qa-card[data-id="{question_id}"] .qa-edit-input')
        expect(input_el).to_be_visible(timeout=3000)
        input_el.fill(new_text)
        input_el.press("Enter")

    def delete_question(self, question_id: str) -> None:
        self._page.locator(f'.qa-card[data-id="{question_id}"] .btn-danger').click()

    def toggle_answered(self, question_id: str) -> None:
        """Click the Answer/Answered toggle button on a question card."""
        self._page.locator(
            f'.qa-card[data-id="{question_id}"] .qa-actions button:first-child'
        ).click()

    # ── Poll History / Download ────────────────────────────────────────────

    def get_poll_history(self) -> list[dict]:
        """Return the poll history stored in host localStorage."""
        return self._page.evaluate("""() => {
            const key = `host_polls_${new Date().toISOString().slice(0, 10)}`;
            try { return JSON.parse(localStorage.getItem(key) || '[]'); } catch { return []; }
        }""")

    def get_download_text(self) -> str:
        """Return the text that downloadPollHistory() would produce."""
        return self._page.evaluate("""() => {
            const key = `host_polls_${new Date().toISOString().slice(0, 10)}`;
            const history = JSON.parse(localStorage.getItem(key) || '[]');
            if (!history.length) return '';
            return history.map((e, n) => {
                const opts = e.options.map((o, i) =>
                    `  ${String.fromCharCode(65+i)}. ${o.text}${o.correct ? ' ✅' : ''}`
                ).join('\\n');
                return `${n+1}. ${e.question}\\n${opts}`;
            }).join('\\n\\n');
        }""")

    def expect_question_answered(self, question_id: str, answered: bool = True) -> None:
        card = self._page.locator(f'.qa-card[data-id="{question_id}"]')
        if answered:
            expect(card).to_have_class(lambda c: "qa-answered" in c, timeout=4000)
        else:
            expect(card).not_to_have_class(lambda c: "qa-answered" in c, timeout=4000)
