"""The AI summary can be reviewed fullscreen.

Fullscreen is asked of #summary-view itself, so the proof that the sidebar and
the reaction bar are gone is that the fullscreen element *is* the summary view —
the browser renders nothing outside it.
"""


def test_summary_fullscreen_button_toggles(pax):
    pax.auto_join()
    page = pax._page
    # The capability broadcast lands shortly after the join and re-selects the
    # activity view, so opening the summary before it would be undone.
    page.wait_for_timeout(1500)
    page.evaluate("showView('summary')")

    page.locator("#summary-fs-btn").click()
    page.wait_for_function(
        "() => document.fullscreenElement === document.getElementById('summary-view')",
        timeout=5000,
    )
    assert page.evaluate(
        "document.querySelector('#summary-fs-btn .material-symbols-outlined').textContent"
    ) == "fullscreen_exit"

    page.locator("#summary-fs-btn").click()
    page.wait_for_function("() => !document.fullscreenElement", timeout=5000)
    assert page.evaluate(
        "document.querySelector('#summary-fs-btn .material-symbols-outlined').textContent"
    ) == "fullscreen"
