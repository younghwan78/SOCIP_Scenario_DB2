from __future__ import annotations

import pytest

from scenario_db.reporting.charts import (
    bw_axis_max_gbps,
    bw_chart_records,
    generate_bw_chart_html,
    generate_timing_chart_html,
    timeline_tick_ms,
    timing_frame_bands,
    timing_frame_separator_lines,
    timing_chart_records,
    timing_sequence_annotations,
    timing_yaxis_category_order,
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
            {
                "task_id": "panel#f0",
                "node_id": "panel",
                "hw_name": "Panel",
                "constraint_type": "sink",
                "frame_index": 0,
                "start_ms": 27.0,
                "end_ms": 33.0,
                "duration_ms": 6.0,
            },
            {
                "task_id": "sensor#f1",
                "node_id": "sensor",
                "hw_name": "HP2",
                "constraint_type": "source",
                "frame_index": 1,
                "start_ms": 33.333,
                "end_ms": 51.333,
                "duration_ms": 18.0,
            },
            {
                "task_id": "csis#f1",
                "node_id": "csis",
                "hw_name": "CSIS",
                "edge_type": "OTF",
                "otf_group_id": "otf0#f1",
                "frame_index": 1,
                "start_ms": 33.333,
                "end_ms": 51.333,
                "duration_ms": 18.0,
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
    assert any(row["label"] == "F0 / Sensor In" for row in records)
    assert any(row["label"] == "F0 / Display Out" for row in records)
    assert any(row["otf_group_id"] == "otf0" for row in records)
    assert any(row["edge_type"] == "M2M" for row in records)


def test_timing_chart_helpers_add_sequence_arrows_frame_bands_and_grid_ticks():
    records = timing_chart_records(_evidence())

    annotations = timing_sequence_annotations(records)
    bands = timing_frame_bands(records)

    assert annotations
    assert annotations[0]["showarrow"] is True
    assert annotations[0]["arrowcolor"] == "#64748B"
    assert [band["frame_index"] for band in bands] == [0, 1]
    assert bands[0]["fillcolor"] != bands[1]["fillcolor"]
    assert timeline_tick_ms(24.0) == 5
    assert timeline_tick_ms(64.0) == 10


def test_timing_chart_helpers_add_y_axis_frame_separator_rows():
    records = timing_chart_records(_evidence())

    separators = timing_frame_separator_lines(records)
    category_order = timing_yaxis_category_order(records)

    assert separators == [{"label": "---- Frame 1 start ----", "x0": 0.0, "x1": 51.333}]
    assert "F0 / Display Out" in category_order
    assert "---- Frame 1 start ----" in category_order
    assert "F1 / Sensor In" in category_order
    assert category_order.index("F0 / Display Out") < category_order.index("---- Frame 1 start ----")
    assert category_order.index("---- Frame 1 start ----") < category_order.index("F1 / Sensor In")


def test_bw_chart_records_join_dma_to_timeline_by_node():
    records = bw_chart_records(_evidence())

    assert [row["node_id"] for row in records] == ["isp", "mfc"]
    assert records[0]["start_ms"] == 18.0
    assert records[0]["end_ms"] == 24.0
    assert records[0]["bw_gbps"] == 1.0
    assert records[1]["direction"] == "Read"


def test_bw_axis_max_uses_instantaneous_peak_and_standard_bucket_not_total_sum():
    records = [
        {"start_ms": 0.0, "end_ms": 10.0, "bw_gbps": 2.8},
        {"start_ms": 10.0, "end_ms": 20.0, "bw_gbps": 2.4},
        {"start_ms": 20.0, "end_ms": 30.0, "bw_gbps": 0.3},
    ]

    assert sum(row["bw_gbps"] for row in records) == pytest.approx(5.5)
    assert bw_axis_max_gbps(records) == 3.0


def test_chart_html_contains_plotly_and_legacy_titles():
    timing_html = generate_timing_chart_html(_evidence(), title="FHD30_Recording")
    bw_html = generate_bw_chart_html(_evidence(), title="FHD30_Recording - Bandwidth Timeline")

    assert "Plotly.newPlot" in timing_html
    assert "FHD30_Recording" in timing_html
    assert ("F0 / Sensor In" in timing_html) or ("F0 \\u002f Sensor In" in timing_html)
    assert "---- Frame 1 start ----" in timing_html
    assert "Plotly.newPlot" in bw_html
    assert "Total BW" in bw_html
