from __future__ import annotations

from dashboard.components.simulation_tables import dma_rows, external_device_rows, ip_power_rows


def test_ip_power_rows_preserve_column_order_and_add_total():
    rows = ip_power_rows(
        {
            "kpi": {"total_power_mw": 30.0, "total_power_ma": 10.0},
            "dvfs_breakdown": [
                {
                    "node_id": "isp0",
                    "hw_name": "ISP",
                    "mode": "normal",
                    "ip_ref": "ip-isp",
                    "total_power_mw": 12.0,
                    "width": 1920,
                    "height": 1080,
                    "format": "YUV",
                    "set_clock_mhz": 332,
                    "required_clock_mhz": 250,
                    "dvfs_level": 4,
                    "vdd": "VDD_CAM",
                    "set_voltage_mv": 606.25,
                    "unit_power_mw_mp": 5.0,
                    "active_power_mw": 12.0,
                    "ppc": 4,
                    "input_resolution_mp": 2.0736,
                    "fps": 30,
                }
            ],
        }
    )

    assert list(rows[0])[:8] == [
        "node_id",
        "hw_name",
        "mode",
        "ip_ref",
        "power_mw",
        "power_ma",
        "set_clock_mhz",
        "required_clock_mhz",
    ]
    assert rows[0]["size"] == "1920x1080"
    assert rows[0]["power_ma"] == 4.0
    assert rows[-1]["node_id"] == "total"
    assert rows[-1]["power_mw"] == 12.0


def test_dma_rows_follow_topology_order():
    rows = dma_rows(
        {
            "topology_order": ["sensor", "isp", "mfc"],
            "dma_breakdown": [
                {"node_id": "mfc", "port": "in", "direction": "read", "bw_mbs": 1},
                {"node_id": "isp", "port": "out", "direction": "write", "bw_mbs": 2},
            ],
        }
    )

    assert [row["node_id"] for row in rows] == ["isp", "mfc"]
    assert list(rows[0])[:4] == ["node_id", "port", "direction", "bw_mbs"]


def test_external_device_rows_fall_back_to_trace_rows():
    result = {
        "calculation_trace": {
            "external_devices": [
                {"device_type": "sensor", "node_id": "sensor_front", "fps": 30, "v_valid_ms": 18.9}
            ]
        }
    }

    rows = external_device_rows(result)

    assert rows == [{"device_type": "sensor", "node_id": "sensor_front", "fps": 30, "v_valid_ms": 18.9}]
