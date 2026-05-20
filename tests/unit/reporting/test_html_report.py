from __future__ import annotations

from scenario_db.reporting.html_report import generate_simulation_report_html
from scenario_db.reporting.models import ReportContext


def _evidence() -> dict:
    return {
        "id": "sim-1",
        "scenario_ref": "uc-camera-recording",
        "variant_ref": "FHD30-SDR-H265",
        "sw_baseline_ref": "sw-vendor-v1.2.3",
        "execution_context": {"silicon_rev": "EVT0", "thermal": "normal", "ambient_temp_c": 25},
        "run_info": {"timestamp": "2026-05-21T01:02:03+09:00", "tool": "scenariodb-sim"},
        "kpi": {
            "total_power_mw": 120.0,
            "total_power_ma": 35.294,
            "core_power_mw": 100.0,
            "bw_power_mw": 20.0,
            "total_bw_mbs": 2500.0,
            "hw_time_max_ms": 12.5,
        },
        "external_devices": [
            {
                "device_type": "sensor",
                "name": "HP2",
                "active_size": "1920x1080",
                "fps": 30,
                "format": "RAW10",
            }
        ],
        "dvfs_breakdown": [
            {
                "node_id": "isp",
                "hw_name": "ISP",
                "mode": "Normal",
                "dvfs_group": "CAM",
                "set_clock_mhz": 332,
                "dvfs_level": 4,
                "set_voltage_mv": 606.25,
                "vdd": "VDD_CAM",
                "ppc": 4,
                "unit_power_mw_mp": 9.92,
                "input_resolution_mp": 2.0736,
                "fps": 30,
                "total_power_mw": 100.0,
                "total_power_ma": 29.412,
            }
        ],
        "timing_breakdown": [{"node_id": "isp", "hw_name": "ISP", "hw_time_ms": 12.5}],
        "dma_breakdown": [
            {
                "node_id": "isp",
                "hw_name": "ISP",
                "port": "ISP_WDMA",
                "direction": "write",
                "width": 1920,
                "height": 1080,
                "format": "NV12",
                "bitwidth": 8,
                "compression": "disable",
                "bw_mbs": 93.312,
                "bw_power_mw": 7.465,
                "bw_power_ma": 2.195,
            }
        ],
        "vdd_power": {"VDD_CAM": {"core_mw": 100.0, "bw_mw": 7.465, "total_mw": 107.465}},
    }


def test_simulation_report_html_contains_legacy_sections_and_chart_links():
    html = generate_simulation_report_html(
        _evidence(),
        context=ReportContext(
            evidence_id="sim-1",
            scenario_ref="uc-camera-recording",
            variant_ref="FHD30-SDR-H265",
            project_ref="projectA",
            variant_name="FHD30 Recording",
        ),
        timing_chart_file="projectA-FHD30_Recording_timing_chart.html",
        bw_chart_file="projectA-FHD30_Recording_bw_chart.html",
    )

    assert "<title>FHD30 Recording" in html
    assert "1. Scenario Description" in html
    assert "2. Basic Conditions" in html
    assert "3. DVFS Guide" in html
    assert "4. Power Results" in html
    assert "5. Clock Results" in html
    assert "6. IP Details" in html
    assert "7. DMA Results" in html
    assert "projectA-FHD30_Recording_timing_chart.html" in html
    assert "projectA-FHD30_Recording_bw_chart.html" in html
