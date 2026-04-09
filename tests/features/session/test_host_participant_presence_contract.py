from pathlib import Path


def test_pax_count_renders_active_over_total():
    src = Path("static/host.js").read_text(encoding="utf-8")
    assert "function updateParticipantCountDisplay" in src
    assert "class=\"pax-active-count\"" in src
    assert "class=\"pax-total-count\"" in src
    assert "/</span>" in src


def test_host_css_renders_presence_dot_from_online_offline_row_classes():
    css = Path("static/host.css").read_text(encoding="utf-8")
    assert ".pax-name::before" in css
    assert ".pax-list li.online .pax-name::before" in css
    assert ".pax-list li.offline .pax-name::before" in css
    assert "background: #4caf50;" in css
    assert "background: #e53935;" in css
