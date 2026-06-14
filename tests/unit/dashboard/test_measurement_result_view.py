from __future__ import annotations

from typing import Any

from dashboard.components.evidence_api_client import list_evidence
from dashboard.components import evidence_results_panel
from dashboard.components.measurement_result_view import (
    artifact_rows,
    cpu_cluster_rows,
    frame_budget_status,
    freq_residency_rows,
    kpi_mean,
    kpi_p95,
    kpi_summary_rows,
    measurement_list_rows,
    prediction_measurement_comparison_rows,
    provenance_summary,
    rail_domain,
    sw_task_rows,
    top_sw_task,
    vdd_domain_rows,
    vdd_power_rows,
)


class _Response:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


def _evidence() -> dict[str, Any]:
    return {
        "id": "meas-x",
        "measured_at": "2026-06-10T15:20:00+09:00",
        "execution_context": {"silicon_rev": "EVT1", "sw_baseline_ref": "sw-vendor-v1.2.3", "method": "measurement", "thermal": "room"},
        "provenance": {"device_id": "D1", "build_id": "B1", "collection_tool_versions": {"perfetto": "v47"}},
        "kpi": {
            "total_power_mw": {"mean": 3850.0, "p95": 4010.0, "n": 5, "ci_95": [3787.0, 3913.0]},
            "frame_latency_ms": 28.4,
        },
        "cpu_breakdown": [
            {
                "cluster": "BIG",
                "power_mw": {"mean": 410.0, "p95": 520.0, "n": 5},
                "avg_freq_mhz": 1920.0,
                "util_pct": 31.2,
                "freq_residency": [
                    {"freq_mhz": 2400.0, "ratio": 0.21, "time_ms": 100.0},
                    {"freq_mhz": 1920.0, "ratio": 0.48, "time_ms": 230.0},
                ],
            },
            {"cluster": "LIT", "power_mw": 185.0},
        ],
        "sw_task_timing": [
            {"task": "eis_warp", "cluster": "BIG", "mean_ms": 7.8, "p95_ms": 10.6, "max_ms": 15.1, "count_per_frame": 1.0, "samples": 26800},
        ],
        "vdd_power": {"VDD_CAM": {"mean_mw": 980.0, "p95_mw": 1080.0}},
        "artifacts": [
            {"type": "perfetto_trace", "storage": "fileshare", "path": "a/trace.pb", "sha256": "abc", "bytes": 123},
        ],
    }


def test_kpi_scalar_helpers():
    assert kpi_mean({"mean": 3850.0}) == 3850.0
    assert kpi_mean(28.4) == 28.4
    assert kpi_mean({"p95": 1.0}) is None
    assert kpi_p95({"p95": 4010.0}) == 4010.0
    assert kpi_p95(28.4) is None


def test_kpi_summary_rows():
    rows = {r["metric"]: r for r in kpi_summary_rows(_evidence())}
    tp = rows["total_power_mw"]
    assert tp["mean"] == 3850.0
    assert tp["p95"] == 4010.0
    assert tp["ci_95"] == [3787.0, 3913.0]
    assert tp["n"] == 5
    assert rows["frame_latency_ms"]["mean"] == 28.4
    assert rows["frame_latency_ms"]["p95"] is None


def test_cpu_cluster_rows_handles_stat_and_flat_power():
    rows = {r["cluster"]: r for r in cpu_cluster_rows(_evidence())}
    assert rows["BIG"]["power_mean_mw"] == 410.0
    assert rows["BIG"]["power_p95_mw"] == 520.0
    assert rows["BIG"]["avg_freq_mhz"] == 1920.0
    assert rows["LIT"]["power_mean_mw"] == 185.0
    assert rows["LIT"]["power_p95_mw"] is None


def test_freq_residency_rows_flattened_with_cluster():
    rows = freq_residency_rows(_evidence())
    assert {(r["cluster"], r["freq_mhz"]) for r in rows} == {("BIG", 2400.0), ("BIG", 1920.0)}
    assert all(r["ratio"] is not None for r in rows)


def test_sw_task_rows():
    rows = sw_task_rows(_evidence())
    assert rows[0]["task"] == "eis_warp"
    assert rows[0]["p95_ms"] == 10.6
    assert rows[0]["count_per_frame"] == 1.0


def test_vdd_power_rows():
    rows = vdd_power_rows(_evidence())
    assert rows[0] == {"rail": "VDD_CAM", "mean_mw": 980.0, "p95_mw": 1080.0}


def test_vdd_power_rows_triplet_shape():
    ev = {
        "vdd_power": {
            "B5_6S1_VDD_CAM_L": {"voltage_v": 0.6077, "current_ma": 170.29, "power_mw": 103.46, "std_mw": 0.89},
            "B6S2_VDD_SRAM_L": {"voltage_v": 0.7217, "current_ma": 48.73, "power_mw": 35.18, "std_mw": 0.30},
        }
    }
    rows = {r["rail"]: r for r in vdd_power_rows(ev)}
    cam = rows["B5_6S1_VDD_CAM_L"]
    assert cam["voltage_v"] == 0.6077
    assert cam["current_ma"] == 170.29
    assert cam["mean_mw"] == 103.46
    assert cam["std_mw"] == 0.89
    # legacy-only p95 column is fully empty here -> dropped
    assert "p95_mw" not in cam


def test_rail_domain_classifies_known_tokens():
    assert rail_domain("B3_4_5S2_VDD_CPUCL3_BIG_L") == "CPU"
    assert rail_domain("B5_6S3_VDD_CPUCL0_DSU_L") == "CPU"
    assert rail_domain("L1S3_VDD_ICPU_L") == "ICPU"      # ICPU before CPU
    assert rail_domain("B5_6S1_VDD_CAM_L") == "CAM"
    assert rail_domain("B1_2_3_4S1_VDD_G3D0_0P725_L") == "GPU"
    assert rail_domain("B6S4_VDDQ_DRAM_MEM_0P5_T") == "MEM"
    assert rail_domain("B6S2_VDD_SRAM_L") == "MEM"
    assert rail_domain("B5S4_VDDMIF_AP_L") == "MIF"
    assert rail_domain("B4S4_VDD_INT_L") == "INT"
    assert rail_domain("WEIRD_RAIL") == "OTHER"


def test_vdd_domain_rows_aggregates_and_sorts():
    ev = {
        "vdd_power": {
            "B3_4_5S2_VDD_CPUCL3_BIG_L": {"power_mw": 30.0},
            "B5_6S3_VDD_CPUCL0_DSU_L": {"power_mw": 70.0},
            "B5_6S1_VDD_CAM_L": {"power_mw": 103.0},
        }
    }
    rows = vdd_domain_rows(ev)
    assert rows[0] == {"domain": "CAM", "power_mw": 103.0}    # sorted desc
    assert rows[1] == {"domain": "CPU", "power_mw": 100.0}    # 30+70 aggregated
    assert {r["domain"] for r in rows} == {"CPU", "CAM"}


def test_vdd_domain_rows_current_ma_source():
    ev = {
        "vdd_power": {
            "B5_6S1_VDD_CAM_L": {"current_ma": 170.3, "power_mw": 103.0},
            "B3_4_5S2_VDD_CPUCL3_BIG_L": {"current_ma": 30.5, "power_mw": 26.9},
        }
    }
    rows = vdd_domain_rows(ev, source_key="current_ma", out_key="current_ma")
    assert rows[0] == {"domain": "CAM", "current_ma": 170.3}
    assert rows[1] == {"domain": "CPU", "current_ma": 30.5}


def test_resolve_domain_map_reads_declared_then_project():
    from dashboard.components import measurement_result_view as mv

    ev = {
        "project_ref": "proj-x",
        "vdd_power": {
            "B3_4_5S2_VDD_CPUCL3_BIG_L": {"current_ma": 30.5, "domain": "CPU"},
            "B5_6S1_VDD_CAM_L": {"current_ma": 170.3},          # no declared domain
        },
    }
    # declared domain on the entry is picked up; undeclared rail is absent (heuristic later)
    m = mv.resolve_domain_map(ev)
    assert m["B3_4_5S2_VDD_CPUCL3_BIG_L"] == "CPU"
    assert "B5_6S1_VDD_CAM_L" not in m

    # per-project override fills rails that have no declared domain; declared still wins
    mv.PROJECT_RAIL_DOMAINS["proj-x"] = {"B5_6S1_VDD_CAM_L": "CAM", "B3_4_5S2_VDD_CPUCL3_BIG_L": "WRONG"}
    try:
        m2 = mv.resolve_domain_map(ev)
        assert m2["B5_6S1_VDD_CAM_L"] == "CAM"
        assert m2["B3_4_5S2_VDD_CPUCL3_BIG_L"] == "CPU"   # declared wins over project
    finally:
        mv.PROJECT_RAIL_DOMAINS.pop("proj-x", None)

    # nothing declared and no project override -> None (caller falls back to heuristic)
    assert mv.resolve_domain_map({"vdd_power": {"R": {"current_ma": 1.0}}}) is None


def test_rail_domain_override_map_wins():
    # token heuristic would say CPU, but the per-project map overrides to MEM
    assert rail_domain("B3_4_5S2_VDD_CPUCL3_BIG_L", {"B3_4_5S2_VDD_CPUCL3_BIG_L": "MEM"}) == "MEM"
    # rails not in the map fall back to the heuristic
    assert rail_domain("B5_6S1_VDD_CAM_L", {"OTHER_RAIL": "MEM"}) == "CAM"


def test_rail_bar_colors_same_domain_shares_family_distinct_shades():
    from dashboard.components.measurement_result_view import rail_bar_colors

    rows = [
        {"rail": "B3_4_5S2_VDD_CPUCL3_BIG_L"},   # CPU
        {"rail": "B5_6S3_VDD_CPUCL0_DSU_L"},     # CPU
        {"rail": "B5_6S1_VDD_CAM_L"},            # CAM
    ]
    colors = rail_bar_colors(rows)
    assert len(colors) == 3
    assert all(c.startswith("rgb(") for c in colors)
    # two CPU rails get distinct shades (different colours)
    assert colors[0] != colors[1]
    # CAM differs from CPU
    assert colors[2] not in (colors[0], colors[1])


def test_unknown_domain_color_is_deterministic():
    from dashboard.components.measurement_result_view import domain_colors

    assert domain_colors(["PROJECT_SPECIFIC_DOMAIN"]) == domain_colors(["PROJECT_SPECIFIC_DOMAIN"])
    assert domain_colors(["PROJECT_SPECIFIC_DOMAIN"]) == ["rgb(208,56,142)"]


def test_frame_budget_status_within_and_exceeds():
    within = frame_budget_status({"kpi": {"frame_latency_ms": {"mean": 28.4, "p95": 32.1, "n": 5400}, "fps_effective": 29.97}})
    assert within["ok"] is True
    assert round(within["budget_ms"], 1) == 33.4
    exceeds = frame_budget_status({"kpi": {"frame_latency_ms": {"mean": 30.0, "p95": 40.0, "n": 100}, "fps_effective": 30.0}})
    assert exceeds["ok"] is False
    assert frame_budget_status({"kpi": {}}) is None


def test_top_sw_task_picks_highest_p95():
    ev = {
        "sw_task_timing": [
            {"task": "a", "p95_ms": 3.8, "cluster": "LIT"},
            {"task": "eis_warp", "p95_ms": 10.6, "cluster": "MID"},
            {"task": "c", "mean_ms": 1.0},
        ]
    }
    top = top_sw_task(ev)
    assert top["task"] == "eis_warp"
    assert top["p95_ms"] == 10.6


def test_artifact_rows_includes_legacy_raw_artifacts():
    ev = _evidence()
    ev["provenance"]["raw_artifacts"] = [{"type": "power_csv", "path": "p.csv", "sha256": "z"}]
    rows = artifact_rows(ev)
    types = [r["type"] for r in rows]
    assert "perfetto_trace" in types
    assert "power_csv" in types


def test_provenance_summary():
    s = provenance_summary(_evidence())
    assert s["method"] == "measurement"
    assert s["device_id"] == "D1"
    assert s["tool_versions"] == {"perfetto": "v47"}


def test_measurement_list_rows():
    rows = measurement_list_rows([_evidence()])
    assert rows[0]["id"] == "meas-x"
    assert rows[0]["sw_version"] == "sw-vendor-v1.2.3"
    assert rows[0]["silicon_rev"] == "EVT1"
    assert rows[0]["total_power_mw"] == 3850.0


def test_prediction_measurement_comparison_rows_show_delta_vs_measurement():
    measurement = _evidence()
    prediction = {
        "id": "proj-x",
        "execution_context": {"method": "projection", "sw_baseline_ref": "sw-vendor-v1.2.3"},
        "kpi": {
            "total_power_mw": 4200.0,
            "total_power_ma": 1235.294,
            "frame_latency_ms": 30.0,
            "prediction_only": 1.0,
        },
    }

    rows = {
        row["metric"]: row
        for row in prediction_measurement_comparison_rows(prediction=prediction, measurement=measurement)
    }

    assert list(rows) == ["total_power_mw", "frame_latency_ms"]
    assert rows["total_power_mw"] == {
        "metric": "total_power_mw",
        "prediction": 4200.0,
        "measurement_mean": 3850.0,
        "measurement_p95": 4010.0,
        "delta_vs_measurement": 350.0,
        "delta_pct_vs_measurement": "9.091%",
        "prediction_current_ma": 1235.294,
        "measurement_current_ma": 1132.353,
        "delta_current_ma": 102.941,
        "vbat_voltage_v": 4.0,
        "pmic_efficiency": 0.85,
    }
    assert rows["frame_latency_ms"]["delta_vs_measurement"] == 1.6
    assert rows["frame_latency_ms"]["delta_pct_vs_measurement"] == "5.634%"


def test_power_current_metric_rows_measurement_first_with_power():
    rows = evidence_results_panel._power_current_metric_rows(
        {
            "metric": "total_power_mw",
            "prediction": 700.0,
            "measurement_mean": 680.0,
            "delta_vs_measurement": 20.0,
            "delta_pct_vs_measurement": "2.941%",
            "prediction_current_ma": 200.315,
            "measurement_current_ma": 198.595,
            "delta_current_ma": 1.72,
            "vbat_voltage_v": 4.0,
            "pmic_efficiency": 0.85,
        }
    )

    # measurement leads; total_power_mw (mW) folded in alongside current (mA)
    assert rows == [
        {"label": "Measurement Power", "value": "680 mW", "delta": None},
        {"label": "Measurement Current", "value": "198.595 mA", "delta": None},
        {"label": "Prediction Power", "value": "700 mW", "delta": "+20 mW (2.941%)"},
        {"label": "Prediction Current", "value": "200.315 mA", "delta": "+1.72 mA vs measurement"},
        {"label": "vBat", "value": "4 V", "delta": None},
        {"label": "PMIC Efficiency", "value": "0.85", "delta": "mA = mW / (vBat x PMIC)"},
    ]


def test_list_evidence_passes_kind_filter():
    captured: dict[str, Any] = {}

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return _Response({"items": [{"id": "meas-x", "kind": "evidence.measurement"}], "total": 1})

    items = list_evidence(
        "http://api/v1",
        fake_request,
        kind="evidence.measurement",
        scenario_ref="uc-camera-recording",
        variant_ref="cam-rec-r1-uhd30-vdis",
    )
    assert items[0]["id"] == "meas-x"
    assert captured["url"].endswith("/evidence")
    assert captured["params"]["kind"] == "evidence.measurement"
    assert captured["params"]["scenario_ref"] == "uc-camera-recording"
    assert captured["params"]["sort_by"] == "measured_at"


def test_evidence_panel_loader_passes_project_filter(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_list_evidence(base_url, **kwargs):
        captured["base_url"] = base_url
        captured.update(kwargs)
        return [{"id": "meas-x"}]

    monkeypatch.setattr(evidence_results_panel, "list_evidence", fake_list_evidence)
    evidence_results_panel._load_evidence_list.clear()
    items, error = evidence_results_panel._load_evidence_list(
        "http://api/v1",
        "evidence.measurement",
        "uc-camera-recording",
        "cam-rec-r1-uhd30-vdis",
        "proj-A-exynos2500",
    )
    evidence_results_panel._load_evidence_list.clear()

    assert error is None
    assert items == [{"id": "meas-x"}]
    assert captured["project_ref"] == "proj-A-exynos2500"


def test_unscoped_evidence_items_only_keeps_legacy_projectless_rows():
    rows = evidence_results_panel._unscoped_evidence_items(
        [
            {"id": "legacy-none", "project_ref": None},
            {"id": "legacy-empty", "project_ref": ""},
            {"id": "project-scoped", "project_ref": "proj-A"},
        ]
    )

    assert [row["id"] for row in rows] == ["legacy-none", "legacy-empty"]


def test_measurement_panel_source_includes_prediction_comparison():
    source = evidence_results_panel.__loader__.get_source(evidence_results_panel.__name__)

    assert "Prediction vs Measurement" in source
    assert "Compare with Prediction" in source
    assert "legacy evidence without project_ref" in source
    assert "prediction_measurement_comparison_rows" in source
