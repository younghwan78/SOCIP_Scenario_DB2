from __future__ import annotations

from pathlib import Path

from dashboard.components.simulation_api_client import export_simulation_artifacts, simulation_artifacts_zip_url
from dashboard.components.simulation_report_actions import report_download_payloads


def _result() -> dict:
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


def test_report_download_payloads_build_three_html_files():
    payloads = report_download_payloads(_result(), project_ref="projectA", variant_name="FHD30 Recording")

    assert [item["file_name"] for item in payloads] == [
        "projectA-FHD30_Recording_timing_chart.html",
        "projectA-FHD30_Recording_bw_chart.html",
        "projectA-FHD30_Recording_simulation_result.html",
    ]
    assert all(item["mime"] == "text/html" for item in payloads)
    assert b"<!DOCTYPE html>" in payloads[-1]["data"]


def test_export_simulation_artifacts_client_posts_request_body():
    calls = []

    class _Response:
        status_code = 200
        text = ""

        def json(self):
            return {"evidence_id": "sim-1", "prefix": "projectA-FHD30_Recording", "output_dir": "E:/reports", "artifacts": []}

    def _request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _Response()

    response = export_simulation_artifacts(
        "http://api/api/v1",
        "sim-1",
        request_func=_request,
        output_dir=str(Path("E:/reports")),
        project_ref="projectA",
        variant_name="FHD30 Recording",
    )

    assert response["prefix"] == "projectA-FHD30_Recording"
    assert calls[0][0] == "POST"
    assert calls[0][1] == "http://api/api/v1/simulation/results/sim-1/artifacts/export"
    assert calls[0][2]["json"]["variant_name"] == "FHD30 Recording"


def test_simulation_artifacts_zip_url_carries_report_context():
    url = simulation_artifacts_zip_url(
        "http://api/api/v1",
        "sim-1",
        project_ref="projectA",
        variant_name="FHD30 Recording",
    )

    assert url == (
        "http://api/api/v1/simulation/results/sim-1/artifacts/download.zip"
        "?project_ref=projectA&variant_name=FHD30+Recording"
    )
