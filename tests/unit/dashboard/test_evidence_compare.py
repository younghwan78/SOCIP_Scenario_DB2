from __future__ import annotations

from dashboard.components.evidence_compare import comparison_rows, context_rows


def test_comparison_rows_show_preview_saved_delta_and_units():
    preview = {
        "kpi": {
            "total_power_mw": 120.5,
            "total_power_ma": 35.0,
            "total_bw_mbs": 800.0,
            "hw_time_max_ms": 20.0,
            "timeline_end_ms": 70.0,
        }
    }
    saved = {
        "kpi": {
            "power_mw": 100.0,
            "power_ma": 40.0,
            "bw_mbs": 500.0,
            "hw_time_ms": 25.0,
            "timeline_end_ms": 60.0,
        }
    }

    rows = comparison_rows(preview, saved)
    by_metric = {row["metric"]: row for row in rows}

    assert by_metric["Power"] == {
        "metric": "Power",
        "preview": 120.5,
        "saved": 100.0,
        "delta": 20.5,
        "delta_pct": "20.500%",
        "unit": "mW",
    }
    assert by_metric["Current"]["delta"] == -5.0
    assert by_metric["Bandwidth"]["unit"] == "MB/s"
    assert by_metric["Critical Path"]["preview"] == "-"


def test_context_rows_compare_ids_and_execution_context_fields():
    preview = {
        "id": "preview-1",
        "scenario_ref": "uc-camera-recording",
        "execution_context": {"silicon_rev": "EVT0", "thermal": "normal"},
        "params_hash": "abc",
    }
    saved = {
        "id": "saved-1",
        "scenario_ref": "uc-camera-recording",
        "execution_context": {"silicon_rev": "EVT1", "thermal": "normal"},
        "params_hash": "abc",
    }

    rows = context_rows(preview, saved)
    by_field = {row["field"]: row for row in rows}

    assert by_field["scenario_ref"]["match"] is True
    assert by_field["silicon_rev"]["preview"] == "EVT0"
    assert by_field["silicon_rev"]["saved"] == "EVT1"
    assert by_field["silicon_rev"]["match"] is False
    assert by_field["params_hash"]["match"] is True
