from __future__ import annotations

from scenario_db.reporting.charts import (
    bw_chart_records,
    generate_bw_chart_html,
    generate_timing_chart_html,
    timing_chart_records,
)


def _evidence() -> dict:
    return {
        "id": "sim-1",
        "scenario_ref": "uc-camera-recording",
        "variant_ref": "FHD30-SDR-H265",
        "topology_order": ["sensor", "csis", "isp", "mfc"],
        "timeline_events": [
            {
                "task_id": "sensor#f0",
                "node_id": "sensor",
                "hw_name": "HP2",
                "constraint_type": "source",
                "frame_index": 0,
                "start_ms": 0.0,
                "end_ms": 18.0,
                "duration_ms": 18.0,
            },
            {
                "task_id": "csis#f0",
                "node_id": "csis",
                "hw_name": "CSIS",
                "edge_type": "OTF",
                "otf_group_id": "otf0#f0",
                "frame_index": 0,
                "start_ms": 0.0,
                "end_ms": 18.0,
                "duration_ms": 18.0,
            },
            {
                "task_id": "isp#f0",
                "node_id": "isp",
                "hw_name": "ISP",
                "edge_type": "M2M",
                "frame_index": 0,
                "start_ms": 18.0,
                "end_ms": 24.0,
                "duration_ms": 6.0,
            },
            {
                "task_id": "mfc#f0",
                "node_id": "mfc",
                "hw_name": "MFC",
                "edge_type": "M2M",
                "frame_index": 0,
                "start_ms": 24.0,
                "end_ms": 30.0,
                "duration_ms": 6.0,
            },
        ],
        "dma_breakdown": [
            {
                "node_id": "isp",
                "hw_name": "ISP",
                "port": "ISP_WDMA",
                "direction": "write",
                "bw_mbs": 1000.0,
                "bw_power_mw": 80.0,
                "bw_power_ma": 23.5,
            },
            {
                "node_id": "mfc",
                "hw_name": "MFC",
                "port": "MFC_RDMA",
                "direction": "read",
                "bw_mbs": 500.0,
                "bw_power_mw": 40.0,
                "bw_power_ma": 11.8,
            },
        ],
    }


def test_timing_chart_records_group_events_by_timeline_fields():
    records = timing_chart_records(_evidence())

    assert records[0]["label"].startswith("F0 /")
    assert any(row["otf_group_id"] == "otf0" for row in records)
    assert any(row["edge_type"] == "M2M" for row in records)


def test_bw_chart_records_join_dma_to_timeline_by_node():
    records = bw_chart_records(_evidence())

    assert [row["node_id"] for row in records] == ["isp", "mfc"]
    assert records[0]["start_ms"] == 18.0
    assert records[0]["end_ms"] == 24.0
    assert records[0]["bw_gbps"] == 1.0
    assert records[1]["direction"] == "Read"


def test_chart_html_contains_plotly_and_legacy_titles():
    timing_html = generate_timing_chart_html(_evidence(), title="FHD30_Recording")
    bw_html = generate_bw_chart_html(_evidence(), title="FHD30_Recording - Bandwidth Timeline")

    assert "Plotly.newPlot" in timing_html
    assert "FHD30_Recording" in timing_html
    assert "Plotly.newPlot" in bw_html
    assert "Total BW" in bw_html
