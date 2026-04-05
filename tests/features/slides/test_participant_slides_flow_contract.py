from pathlib import Path


def _load_slide_function_source() -> str:
    source = Path("static/participant.js").read_text(encoding="utf-8")
    start = source.index("async function _loadSlideIntoViewer")
    end = source.index("async function _reloadCurrentSlideAfterUpdate")
    return source[start:end]


def test_load_slide_checks_cache_before_pdf_fetch():
    src = _load_slide_function_source()
    check_idx = src.index("_checkSlideReady")
    head_idx = src.index("await _fetchSlideHeaders")
    pdf_idx = src.index("slidesPdfLib.getDocument")

    assert check_idx < head_idx
    assert check_idx < pdf_idx


def test_load_slide_bails_out_on_check_failure_without_try_download_link():
    src = _load_slide_function_source()
    check_catch_idx = src.index("Slide is still preparing on the server")
    download_link_idx = src.index("_setSlidesError('', slideDownloadUrl + '?download=1')")
    assert check_catch_idx < download_link_idx
