from __future__ import annotations

from dashboard.components.evidence_debug_trace import (
    dma_trace_rows,
    ip_trace_rows,
    kpi_trace_rows,
    otf_group_trace_rows,
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
                "power": {"result_mw": 12.5},
                "timing": {"result_ms": 4.0},
            }
        ],
        "dma": [
            {
                "node_id": "isp0",
                "port": "wdma",
                "direction": "write",
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
            ]
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
    assert dma_trace_rows(trace)[0]["format_bpp_factor"] == 1.5
    assert otf_group_trace_rows(trace)[0]["bottleneck_tasks"] == ["pdp"]


def test_debug_trace_row_builders_tolerate_missing_sections():
    assert kpi_trace_rows({}) == []
    assert ip_trace_rows({"ip": [None, "bad"]}) == []
    assert dma_trace_rows({"dma": [None, "bad"]}) == []
    assert otf_group_trace_rows({"timeline": {"otf_groups": [None, "bad"]}}) == []
