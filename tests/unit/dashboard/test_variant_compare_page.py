from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from dashboard.components.compare_views import (
    dma_diff,
    domain_chart_rows,
    evidence_kind_label,
    kpi_side_by_side,
    pm_rows,
    unit_diff,
)

PAGE = Path(__file__).resolve().parents[3] / "dashboard" / "pages" / "2_Variant_Compare.py"


def _row(producer, buffer, consumer, size="1920x1080", fmt="YUV420", comp="COMP_OFF"):
    return {"Producer": producer, "Buffer": buffer, "Consumer": consumer, "Size": size, "Format": fmt,
            "Bit": 8, "Compression": comp, "WDMA port": "", "RDMA port": ""}


def test_dma_diff_marks_added_removed_and_changed_first():
    a = [_row("MCSC", "VIDEO", "GDC"), _row("MLSC", "LME_IN", "LME"), _row("GDC", "OUT", "MFC")]
    b = [_row("MCSC", "VIDEO", "GDC", size="3840x2160"), _row("GDC", "OUT", "MFC"), _row("MFC", "ES", "CPU")]
    rows = dma_diff(a, b)
    assert [row["status"] for row in rows] == ["B only", "A only", "changed", "same"]
    assert rows[2]["change"] == "Size: 1920x1080 → 3840x2160"


def test_unit_diff_and_kpi_side_by_side():
    view_a = {"nodes": [{"data": {"id": "a", "label": "LME", "type": "ip"}}, {"data": {"id": "b", "label": "MFC", "type": "ip"}}]}
    view_b = {"nodes": [{"data": {"id": "b", "label": "MFC", "type": "ip"}}, {"data": {"id": "c", "label": "EIS", "type": "sw"}}]}
    assert unit_diff(view_a, view_b) == {"common": ["MFC"], "a_only": ["LME"], "b_only": ["EIS"]}
    rows = kpi_side_by_side({"kpi": {"total_power_mw": 600}}, {"kpi": {"total_power_mw": {"mean": 660}}})
    assert rows == [{"KPI": "Total power", "unit": "mW", "A": 600.0, "B": 660.0, "Δ (B−A)": 60.0, "Δ%": 10.0}]


def test_evidence_labels_flag_synthetic_measurements():
    assert evidence_kind_label({"kind": "evidence.measurement", "id": "meas-synthetic-x"}) == "synthetic"
    assert evidence_kind_label({"kind": "evidence.measurement", "id": "meas-real"}) == "measured"
    assert evidence_kind_label({"kind": "evidence.simulation", "id": "sim"}) == "calculated"


def test_pm_rows_and_domain_chart_rows():
    result = {"rows": [
        {"metric_id": "power.domain", "scope_ref": "CPU", "unit": "mW", "prediction": 180.0, "measurement": 264.6,
         "delta": -84.6, "delta_pct": -32.0, "status": "MATCHED"},
        {"metric_id": "timing.frame_latency", "scope_ref": "self", "unit": "ms", "prediction": None, "measurement": 28.4,
         "status": "MEASUREMENT_ONLY"},
    ]}
    assert [row["metric"] for row in pm_rows(result, metric_filter="latency")] == ["timing.frame_latency"]
    assert domain_chart_rows(result) == [{"domain": "CPU", "side": "예측", "mW": 180.0}, {"domain": "CPU", "side": "실측", "mW": 264.6}]


def _install(monkeypatch):
    from dashboard.components import viewer_api_client
    from scenario_db.view.demo.sample_data import build_sample_level0  # noqa: F401

    variants = [
        {"id": "uhd30-sdr", "design_conditions": {"resolution": "UHD", "fps": 30, "stabilization": 0}},
        {"id": "uhd30-vdis", "design_conditions": {"resolution": "UHD", "fps": 30, "stabilization": "SWVDIS"}},
        {"id": "fhd30-sdr", "design_conditions": {"resolution": "FHD", "fps": 30, "stabilization": 0}},
    ]

    def request(method, api_base, path, **kwargs):
        params = kwargs.get("params") or {}
        if path == "/soc-platforms":
            return {"items": [{"id": "soc-a"}]}
        if path == "/projects":
            return {"items": [{"id": "proj-a"}]}
        if path == "/scenarios":
            return {"items": [{"id": "uc-rec"}]}
        if path.endswith("/variants"):
            return {"items": variants}
        if path.endswith("/view"):
            variant = path.split("/variants/")[1].split("/")[0]
            from scenario_db.view.demo.sample_data import build_sample_level0
            view = build_sample_level0()
            view.scenario_id, view.variant_id, view.level = "uc-rec", variant, 1
            return view.model_dump(mode="json")
        if path == "/evidence":
            if params.get("variant_ref") == "uhd30-vdis":
                return {"items": [
                    {"id": "sim-1", "kind": "evidence.simulation", "kpi": {"total_power_mw": 681.0}},
                    {"id": "meas-1", "kind": "evidence.measurement", "kpi": {"total_power_mw": {"mean": 675.2}}},
                ]}
            return {"items": [{"id": "sim-0", "kind": "evidence.simulation", "kpi": {"total_power_mw": 600.0}}]}
        if path == "/compare/prediction-measurement":
            return {"context": {"compatible": True, "rows": []}, "summary": {"matched": 1},
                    "rows": [{"metric_id": "power.domain", "scope_ref": "CPU", "unit": "mW", "prediction": 1.0,
                              "measurement": 2.0, "status": "MATCHED"}]}
        raise AssertionError(path)

    monkeypatch.setattr(viewer_api_client, "_request_json", request)
    return request


def test_compare_page_adopts_deep_link_and_renders_tabs(monkeypatch):
    _install(monkeypatch)
    app = AppTest.from_file(str(PAGE), default_timeout=20)
    app.query_params.update({"scenario_id": "uc-rec", "variant_id": "uhd30-vdis", "variant_b": "uhd30-sdr"})
    app.run()
    assert not app.exception, app.exception
    assert app.session_state["compare_a"] == "uhd30-vdis"
    assert app.session_state["compare_b"] == "uhd30-sdr"
    assert [tab.label for tab in app.tabs] == ["조건", "Pipeline 구조", "Evidence KPI (A vs B)", "예측 vs 실측"]
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["조건 차이"] == "1"


def test_compare_page_defaults_b_to_nearest_variant(monkeypatch):
    _install(monkeypatch)
    app = AppTest.from_file(str(PAGE), default_timeout=20)
    app.query_params.update({"scenario_id": "uc-rec", "variant_id": "uhd30-sdr"})
    app.run()
    assert not app.exception, app.exception
    assert app.session_state["compare_b"] in {"uhd30-vdis", "fhd30-sdr"}


def test_rails_without_domain_sorted_by_power():
    from dashboard.components.compare_views import rails_without_domain

    evidence = {"vdd_power": {"CAM": {"power_mw": 103.6}, "MIF": {"power_mw": 42.7, "domain": "MIF"},
                              "INT": {"power_mw": 99.1}}}
    assert rails_without_domain(evidence) == [("CAM", 103.6), ("INT", 99.1)]


def test_kpi_and_dma_matrix_for_n_variants():
    from dashboard.components.compare_views import dma_matrix, kpi_matrix

    rows = kpi_matrix({"a": {"kpi": {"total_power_mw": 100}}, "b": {"kpi": {"total_power_mw": 120}}, "c": None}, "a")
    assert rows == [{"KPI": "Total power (mW)", "a": 100.0, "b": 120.0, "Δ% b": 20.0, "c": None, "Δ% c": None}]
    matrix = dma_matrix({"a": [_row("MCSC", "V", "GDC")], "b": [_row("MCSC", "V", "GDC")], "c": [_row("MCSC", "V", "MFC")]})
    assert [row["transfer"] for row in matrix] == ["MCSC → V → GDC", "MCSC → V → MFC"]
    assert matrix[0]["c"] == "—" and matrix[1]["a"] == "—"


def test_compare_page_multi_mode_from_variants_query(monkeypatch):
    _install(monkeypatch)
    app = AppTest.from_file(str(PAGE), default_timeout=20)
    app.query_params.update({"scenario_id": "uc-rec", "variants": "uhd30-sdr,uhd30-vdis,fhd30-sdr"})
    app.run()
    assert not app.exception, app.exception
    assert app.session_state["compare_mode"] == "다중 (N개)"
    assert app.session_state["compare_multi"] == ["uhd30-sdr", "uhd30-vdis", "fhd30-sdr"]
    assert [tab.label for tab in app.tabs] == ["조건 matrix", "DMA 전송 matrix", "Evidence KPI matrix"]
