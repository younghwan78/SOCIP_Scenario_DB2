from dashboard.components.variant_compare import (
    condition_diff,
    differing_keys,
    medoid_variant_id,
    pivot_rows,
)


def _item(variant_id, parent=None, own=None, **conditions):
    return {"project_id": "p", "scenario_id": "s", "variant_id": variant_id, "design_conditions": conditions,
            "derived_from_variant": parent, "own_condition_keys": own or []}


GROUP = [
    _item("a-first-alpha", resolution="FHD", fps=30, hdr="HDR10"),
    _item("uhd30", resolution="UHD", fps=30, hdr="SDR", bitrate_source="assumed"),
    _item("uhd60", resolution="UHD", fps=60, hdr="SDR"),
    _item("uhd30-sdr", resolution="UHD", fps=30, hdr="SDR"),
    _item("uhd30-explored", parent="uhd30", own=["clock"], resolution="UHD", fps=30, hdr="SDR", clock=400),
]


def test_medoid_ignores_alphabetical_order_and_derived_variants():
    assert medoid_variant_id(GROUP) in {"uhd30", "uhd30-sdr"}
    assert medoid_variant_id(GROUP) != "a-first-alpha"


def test_differing_keys_split_varying_and_constant_and_hide_source_keys():
    keys, constant = differing_keys(GROUP)
    assert keys[:3] == ["resolution", "fps", "hdr"]
    assert "bitrate_source" not in keys and "bitrate_source" not in constant


def test_pivot_compares_derived_variant_with_parent_only_on_own_keys():
    keys, _ = differing_keys(GROUP)
    rows, changed = pivot_rows(GROUP, "uhd30-sdr", keys)
    assert rows[0]["variant"] == "uhd30-sdr" and rows[0]["기준"] == "★" and changed[0] == []
    by_id = {row["variant"]: (row, diff) for row, diff in zip(rows, changed)}
    row, diff = by_id["uhd30-explored"]
    assert row["vs"] == "uhd30" and diff == ["clock"] and row["Δ"] == 1
    row, diff = by_id["uhd60"]
    assert row["vs"] == "uhd30-sdr" and diff == ["fps"]
    assert by_id["uhd30"][0]["assumed"] == "bitrate"


def test_condition_diff_orders_changes_first():
    rows = condition_diff(GROUP[1], GROUP[2])
    assert rows[0] == {"key": "fps", "A": "30", "B": "60", "status": "changed"}
    assert {row["status"] for row in rows} >= {"changed", "same", "A only"}
