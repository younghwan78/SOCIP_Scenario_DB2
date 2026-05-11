from __future__ import annotations

from dashboard.components.evidence_debug_trace import (
    dma_trace_rows,
    dma_formula_rows,
    ip_power_formula_rows,
    ip_trace_rows,
    kpi_trace_rows,
    otf_group_trace_rows,
    timeline_cadence_rows,
    timeline_critical_path_rows,
    timeline_wait_rows,
)


def test_debug_trace_row_builders_flatten_formula_sections():
    trace = {
        "kpi": {
            "total_power_mw": {
                "formula": "core + bw",
                "inputs": {"core": 10, "bw": 2},
                "result": 12,
            }
        },
        "ip": [
            {
                "node_id": "isp0",
                "hw_name": "ISP",
                "mode": "Normal",
                "required_clock": {
                    "before_group_align_mhz": 100,
                    "after_group_align_mhz": 133,
                },
                "dvfs": {
                    "dvfs_group": "CAM",
                    "selected_level": 7,
                    "set_clock_mhz": 133,
                    "set_voltage_mv": 562.5,
                    "vdd": "VDD_CAM",
                    "vdd_leader": "isp0",
                    "feasible": True,
                },
                "power": {
                    "formula": "unit_power_mw_mp * resolution_mp * (set_voltage_mv / 710)^2 * (fps / 30)",
                    "inputs": {
                        "unit_power_mw_mp": 4,
                        "resolution_mp": 2.0,
                        "set_voltage_mv": 710,
                        "reference_voltage_mv": 710,
                        "fps": 30,
                        "reference_fps": 30,
                    },
                    "intermediate": {"voltage_scale": 1.0, "fps_scale": 1.0},
                    "result_mw": 12.5,
                },
                "timing": {"result_ms": 4.0},
            }
        ],
        "dma": [
            {
                "node_id": "isp0",
                "port": "wdma",
                "direction": "write",
                "bw_formula": "comp_ratio * fps * width * height * (bitwidth / 8) * format_bpp_factor * r_w_rate / 1e6",
                "bw_power_formula": "bw_mbs * bw_power_coeff / 1000 * llc_weight",
                "bw_power_ma_formula": "bw_power_mw / vbat / pmic_efficiency",
                "inputs": {
                    "width": 1920,
                    "height": 1080,
                    "fps": 30,
                    "format": "YUV420",
                    "bitwidth": 8,
                    "compression": "COMP_OFF",
                    "comp_ratio": 1,
                    "llc_enabled": True,
                },
                "intermediate": {"format_bpp_factor": 1.5, "llc_weight": 0.5},
                "result": {"bw_mbs": 93.3, "bw_power_mw": 7.1, "bw_power_ma": 2.0},
            }
        ],
        "timeline": {
            "otf_groups": [
                {
                    "group_id": "otf-0",
                    "tasks": ["csis", "pdp"],
                    "bottleneck_tasks": ["pdp"],
                    "start_ms": 0,
                    "end_ms": 10,
                }
            ],
            "cadence": [{"task_id": "panel#f1", "cadence_avg_interval_ms": 33.3}],
            "critical_path": [{"task_id": "gdc#f1", "critical_path_rank": 0}],
            "top_waits": [{"task_id": "gdc#f1", "resource_wait_ms": 1.2}],
        },
    }

    assert kpi_trace_rows(trace) == [
        {
            "kpi": "total_power_mw",
            "formula": "core + bw",
            "inputs": {"core": 10, "bw": 2},
            "result": 12,
        }
    ]
    assert ip_trace_rows(trace)[0]["required_after_group_mhz"] == 133
    assert ip_trace_rows(trace)[0]["vdd_leader"] == "isp0"
    assert ip_power_formula_rows(trace)[0]["formula"].startswith("unit_power_mw_mp")
    assert ip_power_formula_rows(trace)[0]["result_mw"] == 12.5
    assert dma_trace_rows(trace)[0]["format_bpp_factor"] == 1.5
    assert dma_formula_rows(trace)[0]["bw_power_formula"] == "bw_mbs * bw_power_coeff / 1000 * llc_weight"
    assert dma_formula_rows(trace)[0]["bw_power_mw"] == 7.1
    assert otf_group_trace_rows(trace)[0]["bottleneck_tasks"] == ["pdp"]
    assert otf_group_trace_rows(trace)[0]["span_ms"] == 10
    assert timeline_cadence_rows(trace)[0]["task_id"] == "panel#f1"
    assert timeline_critical_path_rows(trace)[0]["critical_path_rank"] == 0
    assert timeline_wait_rows(trace)[0]["resource_wait_ms"] == 1.2


def test_debug_trace_row_builders_tolerate_missing_sections():
    assert kpi_trace_rows({}) == []
    assert ip_trace_rows({"ip": [None, "bad"]}) == []
    assert ip_power_formula_rows({"ip": [None, "bad"]}) == []
    assert dma_trace_rows({"dma": [None, "bad"]}) == []
    assert dma_formula_rows({"dma": [None, "bad"]}) == []
    assert otf_group_trace_rows({"timeline": {"otf_groups": [None, "bad"]}}) == []
    assert timeline_cadence_rows({"timeline": {"cadence": [None, "bad"]}}) == []
    assert timeline_critical_path_rows({"timeline": {"critical_path": [None, "bad"]}}) == []
    assert timeline_wait_rows({"timeline": {"top_waits": [None, "bad"]}}) == []


def test_otf_group_trace_rows_backfill_span_from_start_end():
    trace = {"timeline": {"otf_groups": [{"group_id": "otf-0", "start_ms": 3.5, "end_ms": 9.25}]}}

    assert otf_group_trace_rows(trace)[0]["span_ms"] == 5.75
