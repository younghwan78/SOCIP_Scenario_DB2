from __future__ import annotations

from dashboard.components.table_actions import table_height


def test_table_height_expands_with_rows_without_a_cap():
    small = table_height([{"a": 1}])
    large = table_height([{"a": index} for index in range(40)])

    assert small >= 132
    assert large > 1700
    assert large > small
