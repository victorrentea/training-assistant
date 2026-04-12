from pathlib import Path


PARTICIPANT_CODE_HTML = Path("static/new/code.html")


def test_git_repos_header_does_not_render_branch_suffix_text():
    source = PARTICIPANT_CODE_HTML.read_text(encoding="utf-8")
    assert ":' + repo.branch + '</span>'" not in source


def test_git_repos_file_items_link_to_branch_blob_paths():
    source = PARTICIPANT_CODE_HTML.read_text(encoding="utf-8")
    assert "/blob/' + repo.branch + '/' + f" in source


def test_pdf_page_number_badge_is_not_rendered():
    source = PARTICIPANT_CODE_HTML.read_text(encoding="utf-8")
    assert 'id="pdf-page-info"' not in source
