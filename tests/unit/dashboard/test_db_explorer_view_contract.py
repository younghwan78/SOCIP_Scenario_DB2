from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB_EXPLORER = ROOT / "dashboard" / "pages" / "1_DB_Explorer.py"


def _source() -> str:
    return DB_EXPLORER.read_text(encoding="utf-8")


def _sidebar_source(source: str) -> str:
    return source.split("with st.sidebar:", 1)[1].split("filters = {", 1)[0]


def test_db_explorer_uses_icon_quick_picker_for_scenario_category() -> None:
    source = _source()

    assert "_CATEGORY_ICON_LABELS" in source
    assert "_catalog_items_for_category" in source
    assert "explorer_category_choice" in source
    assert "Scenario Type" in source
    assert "st.pills(" in source


def test_db_explorer_hides_domain_picker_when_scenario_type_implies_domain() -> None:
    source = _source()

    assert "len(domain_options) > 1" in source
    assert "Inferred Domain" in source
    assert "explorer_domain_filter" in source


def test_db_explorer_sidebar_keeps_only_global_context_filters() -> None:
    sidebar = _sidebar_source(_source())

    assert 'st.multiselect("Category"' not in sidebar
    assert 'st.multiselect("Domain"' not in sidebar
    assert 'st.multiselect("Scenario"' not in sidebar
    assert 'st.multiselect("Variant Severity"' not in sidebar
    assert "Advanced filters" in sidebar


def test_db_explorer_overview_prioritizes_readable_cards_over_raw_tables() -> None:
    source = _source()

    assert "_render_distribution_cards" in source
    assert "_render_import_batch_cards" in source
    assert "Variant Load Mix" in source
    assert "Board Coverage" in source
    assert "Raw summary tables" in source
