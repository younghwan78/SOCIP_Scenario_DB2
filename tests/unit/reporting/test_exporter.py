from __future__ import annotations

from pathlib import Path

from scenario_db.reporting.exporter import (
    artifact_metadata,
    build_report_context,
    generate_report_bundle,
    write_report_bundle,
)


def _evidence() -> dict:
    return {
        "id": "sim-1",
        "scenario_ref": "uc-camera-recording",
        "variant_ref": "FHD30-SDR-H265",
        "project_ref": "projectA",
        "run_info": {"timestamp": "2026-05-21T01:02:03+09:00", "tool": "scenariodb-sim"},
        "execution_context": {"silicon_rev": "EVT0", "sw_baseline_ref": "sw-vendor-v1.2.3", "thermal": "normal"},
        "kpi": {"total_power_mw": 120.0, "total_bw_mbs": 1500.0, "hw_time_max_ms": 12.5},
        "external_devices": [{"device_type": "sensor", "name": "HP2", "active_size": "1920x1080", "fps": 30}],
        "dvfs_breakdown": [{"node_id": "isp", "hw_name": "ISP", "mode": "Normal", "set_clock_mhz": 332}],
        "timing_breakdown": [{"node_id": "isp", "hw_time_ms": 12.5}],
        "timeline_events": [
            {
                "task_id": "isp#f0",
                "node_id": "isp",
                "hw_name": "ISP",
                "frame_index": 0,
                "start_ms": 1.0,
                "end_ms": 3.0,
                "duration_ms": 2.0,
            }
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
            }
        ],
    }


def test_generate_report_bundle_uses_legacy_file_suffixes():
    context = build_report_context(_evidence(), variant_name="FHD30 Recording")
    bundle = generate_report_bundle(_evidence(), context=context)

    assert bundle.prefix == "projectA-FHD30_Recording"
    assert "Plotly.newPlot" in bundle.timing_chart_html
    assert "Plotly.newPlot" in bundle.bw_chart_html
    assert "projectA-FHD30_Recording_bw_chart.html" in bundle.simulation_report_html


def test_write_report_bundle_creates_three_html_files_and_metadata(tmp_path: Path):
    context = build_report_context(_evidence(), variant_name="FHD30 Recording")
    written = write_report_bundle(_evidence(), context=context, output_dir=tmp_path)

    paths = {artifact.type: artifact.path for artifact in written.artifacts}
    assert sorted(paths) == ["bw_chart", "simulation_report", "timing_chart"]
    assert paths["timing_chart"].name == "projectA-FHD30_Recording_timing_chart.html"
    assert paths["bw_chart"].exists()
    assert paths["simulation_report"].read_text(encoding="utf-8").startswith("<!DOCTYPE html>")

    metadata = artifact_metadata(written)
    assert metadata[0]["storage"] == "local_file"
    assert metadata[0]["sha256"]
    assert metadata[0]["path"] == str(paths[metadata[0]["type"]])
