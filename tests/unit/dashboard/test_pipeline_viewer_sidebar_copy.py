from __future__ import annotations

from pathlib import Path


def test_level2_sidebar_uses_drilldown_target_copy_instead_of_expand_ip():
    source = Path("dashboard/pages/2_Pipeline_Viewer.py").read_text(encoding="utf-8")

    assert '"Drill-down target (Level 2)"' in source
    assert '"Expand IP (Level 2)"' not in source
    assert '"Custom IP/node id"' in source


def test_level2_sidebar_selectbox_uses_stable_string_values_and_context_key():
    source = Path("dashboard/pages/2_Pipeline_Viewer.py").read_text(encoding="utf-8")

    assert "level2_option_labels = {option.value: option.label for option in level2_options}" in source
    assert "option_values," in source
    assert "format_func=lambda value: level2_option_labels.get(value, value)," in source
    assert "key=f\"viewer_level2_target_select_{_state_key_suffix(current_expand_context)}\"" in source
