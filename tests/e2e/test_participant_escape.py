"""Regression test: Escape closes all participant modals."""


def test_escape_closes_all_participant_modals(pax):
    pax.join("EscModal")
    page = pax._page

    page.evaluate("""() => {
        document.getElementById('notes-overlay')?.classList.add('open');
        document.getElementById('summary-overlay')?.classList.add('open');
        document.getElementById('slides-overlay')?.classList.add('open');
        showLetterAvatarModal('VR', '#345678');
    }""")

    page.wait_for_function("""() => {
        return document.getElementById('notes-overlay')?.classList.contains('open') &&
               document.getElementById('summary-overlay')?.classList.contains('open') &&
               document.getElementById('slides-overlay')?.classList.contains('open') &&
               !!document.getElementById('avatar-modal');
    }""")

    page.keyboard.press('Escape')

    page.wait_for_function("""() => {
        return !document.getElementById('notes-overlay')?.classList.contains('open') &&
               !document.getElementById('summary-overlay')?.classList.contains('open') &&
               !document.getElementById('slides-overlay')?.classList.contains('open') &&
               !document.getElementById('avatar-modal');
    }""")
