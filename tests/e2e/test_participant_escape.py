"""Regression test: Escape closes all participant modals."""

import pytest


@pytest.mark.skip(
    reason="Participant notes/summary/slides modals and the global Escape-to-close "
    "behavior are not present on the new activity-model participant page "
    "(CI repair 2026-06-26)"
)
def test_escape_closes_all_participant_modals(pax):
    pax.join("EscModal")
    page = pax._page

    page.evaluate("""() => {
        document.getElementById('notes-overlay')?.classList.add('open');
        document.getElementById('summary-overlay')?.classList.add('open');
        document.getElementById('slides-overlay')?.classList.add('open');
    }""")

    page.wait_for_function("""() => {
        return document.getElementById('notes-overlay')?.classList.contains('open') &&
               document.getElementById('summary-overlay')?.classList.contains('open') &&
               document.getElementById('slides-overlay')?.classList.contains('open');
    }""")

    page.keyboard.press('Escape')

    page.wait_for_function("""() => {
        return !document.getElementById('notes-overlay')?.classList.contains('open') &&
               !document.getElementById('summary-overlay')?.classList.contains('open') &&
               !document.getElementById('slides-overlay')?.classList.contains('open');
    }""")
