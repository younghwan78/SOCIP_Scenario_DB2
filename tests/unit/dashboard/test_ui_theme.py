from __future__ import annotations

from dashboard.components import ui_theme


def test_sidebar_toggle_script_restores_inner_overflow_after_reexpand():
    script = ui_theme._sidebar_toggle_script(sidebar_width=288, logo_src="")

    assert 'inner.style.setProperty("overflow", "visible", "important")' in script
    assert 'inner.style.removeProperty("overflow")' in script
    assert 'inner.style.removeProperty("overflow-x")' in script
    assert 'inner.style.removeProperty("overflow-y")' in script
