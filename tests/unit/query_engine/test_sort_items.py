from __future__ import annotations

from scenario_db.api.schemas.query import QueryResultItem
from scenario_db.query_engine.service import _sort_items


def _item(variant_id: str, resolution) -> QueryResultItem:
    return QueryResultItem(
        project_id="proj-demo",
        scenario_id="uc-camera",
        scenario_name="Camera",
        variant_id=variant_id,
        design_conditions={"resolution": resolution} if resolution is not None else {},
    )


def test_sort_items_handles_mixed_numeric_and_text_values():
    """Regression: mixed float/str axis values must not raise TypeError."""
    items = [
        _item("v-text", "4K"),
        _item("v-number", 1080),
        _item("v-missing", None),
        _item("v-numeric-text", "720"),
    ]

    result = _sort_items(items, [{"field": "axis.resolution", "dir": "asc"}])

    # Numbers (including numeric strings) first, then text, then missing.
    assert [item.variant_id for item in result] == [
        "v-numeric-text",
        "v-number",
        "v-text",
        "v-missing",
    ]


def test_sort_items_mixed_values_desc_does_not_raise():
    items = [_item("v-text", "4K"), _item("v-number", 1080)]

    result = _sort_items(items, [{"field": "axis.resolution", "dir": "desc"}])

    assert [item.variant_id for item in result] == ["v-text", "v-number"]
