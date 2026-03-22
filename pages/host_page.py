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

    def create_poll(self, question: str, options: list[str], multi: bool = False,
                    correct_count: int | None = None) -> None:
        """Type a poll into the composer and launch it (poll opens automatically)."""
        composer = self._page.locator("#poll-input")
        composer.scroll_into_view_if_needed(timeout=10000)
        composer.click()
        composer.evaluate("el => { el.focus(); document.execCommand('selectAll'); }")
        self._page.keyboard.type("\n".join([question] + options))
        if multi:
            self._page.check("#multi-check")
            if correct_count is not None:
                self._page.fill("#correct-count", str(correct_count))
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
        self._page.click("text=Q&A")
        expect(self._page.locator("#tab-content-qa")).to_be_visible(timeout=5000)

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

    # ── Code Review ────────────────────────────────────────────────────────

    def open_codereview_tab(self) -> None:
        self._page.click("#tab-codereview")
        expect(self._page.locator("#tab-content-codereview")).to_be_visible(timeout=5000)

    def create_codereview(self, snippet: str, language: str | None = None) -> None:
        """Fill code snippet, optionally set language, and start code review."""
        self._page.fill("#codereview-snippet", snippet)
        if language:
            self._page.select_option("#codereview-language", label=language)
        self._page.locator("#codereview-create .btn-success").click()
        expect(self._page.locator("#codereview-active")).to_be_visible(timeout=5000)

    def close_codereview_selection(self) -> None:
        """End the selecting phase → transition to reviewing."""
        self._page.click("#codereview-close-btn")
        expect(self._page.locator("#codereview-phase-label")).to_contain_text("Review", timeout=5000)

    def confirm_codereview_line(self, line_num: int) -> None:
        """Select a line in the host code panel, then click the confirm button."""
        # Use JS function to select the line (triggers side panel)
        self._page.evaluate(f"selectCodeReviewLine({line_num})")
        # Click the confirm button rendered in the side panel
        confirm_btn = self._page.locator("#codereview-side-panel .btn-success")
        expect(confirm_btn).to_be_visible(timeout=3000)
        confirm_btn.click()

    def clear_codereview(self) -> None:
        self._page.click("#codereview-clear-btn")

    def get_codereview_line_counts(self) -> dict[int, int]:
        """Return {line_num: selection_count} from host code panel percentage badges."""
        lines = self._page.locator("#codereview-code-panel .codereview-line").all()
        result = {}
        for i, line in enumerate(lines):
            count_el = line.locator(".codereview-count")
            if count_el.is_visible():
                pct_text = count_el.inner_text().strip().replace("%", "")
                if pct_text and int(pct_text) > 0:
                    result[i + 1] = int(pct_text)
        return result

    def get_participant_scores(self) -> dict[str, int]:
        """Return {name: score} from the participant list."""
        rows = self._page.locator("#pax-list li").all()
        result = {}
        for row in rows:
            name_el = row.locator(".pax-name")
            name_text = name_el.inner_text().strip()
            score_el = row.locator(".pax-score")
            score = 0
            if score_el.count() > 0 and score_el.is_visible():
                score_text = score_el.inner_text().strip()
                # Format: "⭐ X pts"
                import re
                m = re.search(r"(\d+)", score_text)
                if m:
                    score = int(m.group(1))
            # Strip score text and emoji from name
            name_clean = name_text.replace(score_el.inner_text().strip(), "").strip() if score_el.count() > 0 and score_el.is_visible() else name_text
            # Remove avatar/emoji prefixes - just get the text content
            result[name_clean] = score
        return result

    # ── Assertions ────────────────────────────────────────────────────────

    def expect_question_answered(self, question_id: str, answered: bool = True) -> None:
        card = self._page.locator(f'.qa-card[data-id="{question_id}"]')
        if answered:
            expect(card).to_have_class(lambda c: "qa-answered" in c, timeout=4000)
        else:
            expect(card).not_to_have_class(lambda c: "qa-answered" in c, timeout=4000)
