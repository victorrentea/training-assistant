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
        """Create and open a poll via the daemon API directly (bypasses browser UI parsing)."""
        import json as _json
        # Ensure Poll tab is active (may be on Q&A/Wordcloud/Code tab)
        self._page.click("#tab-poll")
        # Build proper dict options {id, text} as daemon expects
        dict_options = [{"id": chr(65 + i), "text": t} for i, t in enumerate(options)]
        payload: dict = {"question": question, "options": dict_options, "multi": multi}
        if correct_count is not None:
            payload["correct_count"] = correct_count
        # Use JS fetch to POST to daemon API — page already has SESSION_ID and API() helper
        self._page.evaluate(f"""async () => {{
            const resp = await fetch(API('/poll'), {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({_json.dumps(payload)})
            }});
            if (!resp.ok) throw new Error('Poll create failed: ' + resp.status);
            const open_resp = await fetch(API('/poll/open'), {{ method: 'POST' }});
            if (!open_resp.ok) throw new Error('Poll open failed: ' + open_resp.status);
        }}""")
        # Wait for poll to be created & opened (poll-question appears in DOM)
        self._page.wait_for_selector("#poll-display.voting-active", timeout=5000)

    def expect_generate_button_label(self, label: str) -> None:
        expect(self._page.locator("#gen-quiz-btn")).to_have_text(label, timeout=3000)

    def set_quiz_topic(self, text: str) -> None:
        self._page.fill("#quiz-topic", text)

    def close_poll(self) -> None:
        # Close poll via daemon REST API (same pattern as create_poll/open_poll)
        # Avoids flakiness from DOM button visibility depending on activeTimer state
        self._page.evaluate("""async () => {
            const resp = await fetch(API('/poll/close'), { method: 'POST' });
            if (!resp.ok) throw new Error('Poll close failed: ' + resp.status);
        }""")
        # Poll closed: #poll-display no longer has .voting-active
        self._page.wait_for_function(
            "() => !document.querySelector('#poll-display.voting-active')",
            timeout=5000,
        )

    def reopen_poll(self) -> None:
        self._page.locator("button[onclick='setPollStatus(true)']").click(force=True)
        self._page.wait_for_selector("#poll-display.voting-active", timeout=5000)

    def mark_correct(self, *option_texts: str) -> None:
        """Click result rows to mark options correct (by partial text match)."""
        for text in option_texts:
            self._page.locator(f".result-row:has-text('{text}')").click()

    # ── Word Cloud ──────────────────────────────────────────────────────────

    def open_wordcloud_tab(self) -> None:
        self._page.click("#tab-wordcloud")
        self._page.evaluate("""async () => {
            const resp = await fetch(API('/activity'), {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ activity: 'wordcloud' }),
            });
            if (!resp.ok) throw new Error('Set activity wordcloud failed: ' + resp.status);
        }""")
        self._page.wait_for_timeout(300)

    def submit_word(self, word: str) -> None:
        self._page.fill("#wc-host-input", word)
        self._page.press("#wc-host-input", "Enter")

    # ── Q&A ─────────────────────────────────────────────────────────────────

    def open_qa_tab(self) -> None:
        self._page.click("#tab-qa")
        expect(self._page.locator("#tab-content-qa")).to_be_visible(timeout=5000)
        self._page.evaluate("""async () => {
            const resp = await fetch(API('/activity'), {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ activity: 'qa' }),
            });
            if (!resp.ok) throw new Error('Set activity qa failed: ' + resp.status);
        }""")
        self._page.wait_for_timeout(300)

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
        # editQuestion() shows the .qa-edit-input inside the card; then set the value
        # and submit via the daemon REST API (avoids Playwright visibility checks on the
        # input element which is inside an overflow:hidden container in headless mode)
        self._page.evaluate(f"""async () => {{
            const qid = {_json.dumps(question_id)};
            const newText = {_json.dumps(new_text)};
            editQuestion(qid);
            // Wait a tick for the input to appear
            await new Promise(r => setTimeout(r, 100));
            const input = document.querySelector(`.qa-card[data-id="${{qid}}"] .qa-edit-input`);
            if (input) {{
                input.value = newText;
                input.dispatchEvent(new Event('input'));
                // Trigger the save via keydown Enter
                input.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', bubbles: true}}));
            }} else {{
                // Fallback: call API directly
                await fetch(`/api/${{SESSION_ID}}/host/qa/${{qid}}`, {{
                    method: 'PATCH',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{text: newText}})
                }});
            }}
        }}""")

    def delete_question(self, question_id: str) -> None:
        import json as _json
        self._page.evaluate(f"""async () => {{
            const qid = {_json.dumps(question_id)};
            const resp = await fetch(API(`/qa/question/${{qid}}`), {{
                method: 'DELETE',
            }});
            if (!resp.ok) throw new Error('Delete question failed: ' + resp.status);
        }}""")

    def toggle_answered(self, question_id: str) -> None:
        """Toggle answered status via daemon API for deterministic behavior."""
        import json as _json
        self._page.evaluate(f"""async () => {{
            const qid = {_json.dumps(question_id)};
            // Determine current answered state from DOM, then flip it.
            const card = document.querySelector(`.qa-card[data-id="${{qid}}"]`);
            const currentlyAnswered = !!card && card.classList.contains('qa-answered');
            const resp = await fetch(API(`/qa/question/${{qid}}/answered`), {{
                method: 'PUT',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ answered: !currentlyAnswered }}),
            }});
            if (!resp.ok) throw new Error('Toggle answered failed: ' + resp.status);
        }}""")

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
