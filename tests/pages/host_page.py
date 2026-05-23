"""
Page Object for the host control panel (/host).
All interactions go through the real browser UI.
"""
from __future__ import annotations

from playwright.sync_api import Page, expect


class HostPage:
    def __init__(self, page: Page):
        self._page = page

    # ── Quiz ────────────────────────────────────────────────────────────────

    def create_quiz(self, question: str, options: list[str], multi: bool = False,
                    correct_count: int | None = None) -> None:
        """Create and open a quiz via the daemon API directly (bypasses browser UI parsing)."""
        import json as _json
        # Ensure Quiz tab is active and activity set on daemon (awaited via JS)
        self._page.evaluate("async () => { await switchTab('quiz'); }")
        # Daemon CreateQuizRequest expects options as a list of strings.
        payload: dict = {"question": question, "options": list(options), "multi": multi}
        if correct_count is not None:
            payload["correct_count"] = correct_count
        # POST /quiz/manual/submit auto-opens the quiz on the daemon side.
        self._page.evaluate(f"""async () => {{
            const resp = await fetch(API('/quiz/manual/submit'), {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({_json.dumps(payload)})
            }});
            if (!resp.ok) throw new Error('Quiz create failed: ' + resp.status);
        }}""")
        # Wait for quiz to be created & opened (quiz-question appears in DOM)
        self._page.wait_for_selector("#quiz-display.voting-active", timeout=5000)

    def expect_generate_button_label(self, label: str) -> None:
        expect(self._page.locator("#gen-quiz-btn")).to_have_text(label, timeout=3000)

    def set_quiz_topic(self, text: str) -> None:
        self._page.fill("#quiz-topic", text)

    def close_quiz(self) -> None:
        # Close quiz via daemon REST API. The host's quiz_ended WS handler
        # (host.js:344) calls fetchQuizState() on its own when the message
        # arrives, so we don't need to do it here. The 250 ms settle gives any
        # in-flight participant votes time to land on the daemon before that
        # WS-driven re-fetch runs — castVote() on the participant is
        # fire-and-forget, so the local "Vote registered" toast appears before
        # the server has acked.
        self._page.evaluate("""async () => {
            const resp = await fetch(API('/quiz/end'), { method: 'POST' });
            if (!resp.ok) throw new Error('Quiz close failed: ' + resp.status);
            await new Promise(r => setTimeout(r, 250));
        }""")
        # Quiz closed: #quiz-display no longer has .voting-active
        self._page.wait_for_function(
            "() => !document.querySelector('#quiz-display.voting-active')",
            timeout=5000,
        )

    def start_timer(self, seconds: int) -> None:
        """Start a countdown timer to end the quiz via daemon API."""
        self._page.evaluate(f"""async () => {{
            const resp = await fetch(API('/quiz/end/timer'), {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ seconds: {seconds} }})
            }});
            if (!resp.ok) throw new Error('Timer start failed: ' + resp.status);
        }}""")

    def start_timer_via_slider(self, seconds: int) -> None:
        """Drive the host UI timer slider — same code path as a real release.

        The slider is rendered with `min="5"`, but the bug we want to reproduce
        is independent of the minimum value. Test code lowers `min` so we can
        send 1s and keep the test fast; the click handler invoked
        (`startTimer(+this.value)`) is identical to a human release.
        """
        self._page.evaluate(f"""() => {{
            const s = document.getElementById('timer-slider');
            if (!s) throw new Error('Timer slider not visible — quiz must be open with no active timer');
            s.min = '1';
            s.value = '{seconds}';
            s.dispatchEvent(new Event('input', {{bubbles: true}}));
            s.dispatchEvent(new Event('mouseup', {{bubbles: true}}));
        }}""")

    def reopen_quiz(self) -> None:
        self._page.locator("button[onclick='setQuizStatus(true)']").click(force=True)
        self._page.wait_for_selector("#quiz-display.voting-active", timeout=5000)

    def mark_correct(self, *option_texts: str) -> None:
        """Click result rows to mark options correct (by partial text match)."""
        for text in option_texts:
            self._page.locator(f".result-row:has-text('{text}')").click()

    def reveal_correct(self, correct_ids: list[str]) -> None:
        """Reveal correct answers and award scores via daemon API.

        Accepts letter IDs ("A", "B", ...) for backwards compatibility with
        existing tests; the daemon's PUT /quiz/correct now expects integer
        indices, so we convert here.
        """
        import json as _json
        indices = [ord(s) - 65 for s in correct_ids]
        self._page.evaluate(f"""async () => {{
            const resp = await fetch(API('/quiz/correct'), {{
                method: 'PUT',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{correct_indices: {_json.dumps(indices)}}})
            }});
            if (!resp.ok) throw new Error('Reveal correct failed: ' + resp.status);
        }}""")

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

    # ── Quiz History / Download ────────────────────────────────────────────

    def get_quiz_history(self) -> list[dict]:
        """Return the quiz history stored in host localStorage."""
        return self._page.evaluate("""() => {
            const key = `host_quizzes_${new Date().toISOString().slice(0, 10)}`;
            try { return JSON.parse(localStorage.getItem(key) || '[]'); } catch { return []; }
        }""")

    def get_download_text(self) -> str:
        """Return the text that downloadQuizHistory() would produce."""
        return self._page.evaluate("""() => {
            const key = `host_quizzes_${new Date().toISOString().slice(0, 10)}`;
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

    def get_vote_count_for(self, option_text: str) -> int:
        """Read the live vote count shown on the host quiz result row for an option."""
        row = self._page.locator(f".result-row:has-text('{option_text}')")
        if row.count() == 0:
            return 0
        return int(row.first.locator(".pct").inner_text().strip() or "0")

    def get_voted_count(self) -> int:
        """Return how many participants have voted (live indicator while quiz is open).

        Reads the #vote-progress-label which is rendered as 'N of M voted'.
        Returns 0 when the quiz is closed (label not present).
        """
        import re as _re
        label = self._page.locator("#vote-progress-label")
        if label.count() == 0 or not label.is_visible():
            return 0
        m = _re.match(r"(\d+) of", label.inner_text().strip())
        return int(m.group(1)) if m else 0

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

    # ── Slides ─────────────────────────────────────────────────────────────

    def open_slides_tab(self) -> None:
        """Switch to slides tab (the default 'none' activity shows slides)."""
        self._page.evaluate("async () => { await switchTab('none'); }")

    def upload_slide(self, slug: str, pdf_bytes: bytes) -> None:
        """Upload a slide PDF via the host UI."""
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", prefix=slug + "-", delete=False) as f:
            f.write(pdf_bytes)
            tmp_path = f.name
        try:
            file_input = self._page.locator('input[type="file"][accept*="pdf"]')
            file_input.set_input_files(tmp_path)
            self._page.wait_for_timeout(2000)  # wait for upload + WS broadcast
        finally:
            os.unlink(tmp_path)

    # ── Assertions ────────────────────────────────────────────────────────

    def expect_question_answered(self, question_id: str, answered: bool = True) -> None:
        card = self._page.locator(f'.qa-card[data-id="{question_id}"]')
        if answered:
            expect(card).to_have_class(lambda c: "qa-answered" in c, timeout=4000)
        else:
            expect(card).not_to_have_class(lambda c: "qa-answered" in c, timeout=4000)

    # ── Poll helpers ──

    def open_poll_tab(self):
        # Wait for host page JS to initialize (WS connected + state fetched)
        # The #tab-quiz being visible indicates the host panel is fully ready
        self._page.wait_for_selector("#tab-quiz", state="visible", timeout=15000)
        self._page.click("#tab-poll")
        # Wait for poll tab to become active
        self._page.wait_for_function(
            "() => document.getElementById('tab-poll') && document.getElementById('tab-poll').classList.contains('active')",
            timeout=5000,
        )
        self._page.wait_for_timeout(200)

    def fill_poll_question(self, text: str):
        self._page.fill("#poll-question", text)

    def add_poll_option(self, text: str):
        """Fills the trailing empty draft row."""
        rows = self._page.locator(".poll-option-row")
        # The last row is always the empty draft
        rows.last.fill(text)

    def toggle_poll_multi(self):
        self._page.click("#poll-multi")

    def toggle_poll_public(self):
        self._page.click("#poll-public")

    def start_poll(self):
        self._page.click("#poll-start-btn")

    def stop_poll(self):
        """End the live poll but keep the draft for editing."""
        self._page.click("#poll-stop-btn")

    def clear_poll(self):
        self._page.click("#poll-clear-btn")

    def poll_results_rows(self):
        """Returns the host live-results rows in current DOM order."""
        return self._page.locator(".poll-bar-row").all()

    def poll_results_row_text(self, idx: int) -> str:
        return self.poll_results_rows()[idx].locator(".label").inner_text()

    def poll_results_row_count(self, idx: int) -> int:
        return int(self.poll_results_rows()[idx].locator(".count").inner_text())
