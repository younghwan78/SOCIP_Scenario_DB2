from __future__ import annotations

from scenario_db.reporting.tables import (
    basic_conditions_rows,
    dma_report_rows,
    dvfs_guide_rows,
    ip_detail_rows,
    power_summary_rows,
    scenario_description_rows,
)


def _evidence() -> dict:
    return {
        "id": "sim-1",
        "scenario_ref": "uc-camera-recording",
        "variant_ref": "FHD30-SDR-H265",
        "execution_context": {
            "silicon_rev": "EVT0",
            "sw_baseline_ref": "sw-vendor-v1.2.3",
            "thermal": "normal",
            "ambient_temp_c": 25.0,
        },
        "run_info": {"timestamp": "2026-05-21T01:02:03+09:00", "tool": "scenariodb-sim"},
        "kpi": {
            "total_power_mw": 120.0,
            "total_power_ma": 35.294,
            "core_power_mw": 100.0,
            "bw_power_mw": 20.0,
            "total_bw_mbs": 2500.0,
            "hw_time_max_ms": 12.5,
            "timeline_end_ms": 33.3,
        },
        "external_devices": [
            {
                "device_type": "sensor",
                "node_id": "sensor",
                "name": "HP2",
                "active_size": "1920x1080",
                "fps": 30,
                "format": "RAW10",
                "v_valid_ms": 18.2,
            }
        ],
        "dvfs_breakdown": [
            {
                "node_id": "isp",
                "ip_ref": "ip-isp",
                "hw_name": "ISP",
                "mode": "Normal",
                "dvfs_group": "CAM",
                "required_clock_mhz": 300.0,
                "set_clock_mhz": 332.0,
                "dvfs_level": 4,
                "required_voltage_mv": 600.0,
                "set_voltage_mv": 606.25,
                "vdd": "VDD_CAM",
                "ppc": 4,
                "unit_power_mw_mp": 9.92,
                "input_resolution_mp": 2.0736,
                "fps": 30.0,
                "total_power_mw": 100.0,
                "total_power_ma": 29.412,
            }
        ],
        "timing_breakdown": [{"node_id": "isp", "hw_time_ms": 12.5}],
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


def test_scenario_description_uses_external_sensor_and_kpi():
    rows = scenario_description_rows(_evidence())

    assert rows["Scenario"] == "uc-camera-recording"
    assert rows["Variant"] == "FHD30-SDR-H265"
    assert rows["Sensor"] == "HP2"
    assert rows["Resolution"] == "1920x1080"
    assert rows["FPS"] == "30"


def test_basic_conditions_include_execution_context_and_run_info():
    rows = basic_conditions_rows(_evidence())

    assert rows["Silicon Rev"] == "EVT0"
    assert rows["SW Baseline"] == "sw-vendor-v1.2.3"
    assert rows["Thermal"] == "normal"
    assert rows["Ambient"] == "25 C"
    assert rows["Tool"] == "scenariodb-sim"


def test_dvfs_power_ip_and_dma_rows_have_legacy_units():
    evidence = _evidence()

    assert dvfs_guide_rows(evidence)[0]["DVFS Domain"] == "CAM"
    assert power_summary_rows(evidence)[0]["VDD"] == "VDD_CAM"
    assert ip_detail_rows(evidence)[0]["HW Time(ms)"] == "12.500"
    assert dma_report_rows(evidence)[0]["BW (MB/s)"] == "93.3"
