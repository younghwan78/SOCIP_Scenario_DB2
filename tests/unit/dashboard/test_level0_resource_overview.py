from __future__ import annotations

from pathlib import Path

from dashboard.components.level0_resource_overview import (
    SUBSYSTEM_ROW_COLORS,
    buffer_handoff_rows,
    display_summary_rows,
    display_layer_rows,
    metric_breakdown_rows,
    resource_overview_rows,
    resource_overview_row_style,
    sensor_summary_rows,
)
from scenario_db.api.schemas.view import (
    DisplayCompositionSummary,
    IoSummary,
    Level0MetricBreakdown,
    Level0ResourceOverview,
    ResourceOverviewRow,
    SensorEndpointSummary,
    ViewResponse,
    ViewSummary,
)


def _view() -> ViewResponse:
    overview = Level0ResourceOverview(
        rows=[
            ResourceOverviewRow(
                sequence_index=1,
                node_id="sensor_rear",
                label="Rear Sensor",
                resource_domain="external_source",
                resource_kind="sensor",
                subsystem="camera",
                output=IoSummary(width=4080, height=2296, fps=30, format="RAW10", bitdepth=10),
                flow="OTF",
                badges=["SENSOR", "OTF"],
            ),
            ResourceOverviewRow(
                sequence_index=2,
                node_id="gpu",
                label="GPU",
                resource_domain="soc_resource",
                resource_kind="gpu",
                subsystem="display",
                input=IoSummary(width=1920, height=1080, fps=60, format="RGBA8888"),
                output=IoSummary(width=1920, height=1080, fps=60, format="RGBA8888"),
                flow="M2M",
                buffer_refs=["GPU_NPU_BUF"],
                badges=["GPU", "M2M", "BUF"],
            ),
        ],
        metric_breakdown=[
            Level0MetricBreakdown(subsystem="camera", node_count=1, bw_total_mbs=1200.0),
            Level0MetricBreakdown(subsystem="display", node_count=1, power_mw=85.5),
        ],
        sensors=[
            SensorEndpointSummary(
                node_id="sensor_rear",
                sensor_mode="wide_video_16_9_30",
                module_ref="ip-sensor-rear-s5e9965",
                output=IoSummary(width=4080, height=2296, fps=30, format="RAW10", bitdepth=10),
                downstream=["csis"],
            )
        ],
        displays=[
            DisplayCompositionSummary(
                node_id="dpu",
                composer="DPU_DIRECT",
                layer_count=3,
                panel_mode="120hz",
                output=IoSummary(width=1920, height=1080, fps=60, format="RGB888"),
                layers=[
                    {
                        "name": "Camera Preview",
                        "buffer_ref": "preview_buf",
                        "format": "NV12",
                        "src_frame": "0,0 1920x1080",
                        "dst_frame": "0,96 1080x1920",
                        "transform": "ROT_90",
                    }
                ],
            )
        ],
    )
    return ViewResponse(
        level=0,
        mode="architecture",
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-r1-fhd30-vdis",
        nodes=[],
        edges=[],
        summary=ViewSummary(
            scenario_id="uc-camera-recording",
            variant_id="cam-rec-r1-fhd30-vdis",
            name="Camera Recording",
            subtitle="FHD 30fps",
            period_ms=33.33,
            budget_ms=30.0,
            resolution="1920 x 1080",
            fps=30,
            variant_label="soc-exynos2600",
        ),
        level0_resource_overview=overview,
    )


def test_level0_resource_overview_formatter_exposes_resource_and_buffer_tables():
    view = _view()

    rows = resource_overview_rows(view)
    buffers = buffer_handoff_rows(view)
    metrics = metric_breakdown_rows(view)

    assert rows[0]["Domain"] == "External Source"
    assert rows[0]["Output"] == "4080x2296 @ 30fps / RAW10 / 10b"
    assert rows[1]["Badges"] == "GPU | M2M | BUF"
    assert buffers == [{"Buffer": "GPU_NPU_BUF", "Producer": "gpu", "Subsystem": "display", "Output": "1920x1080 @ 60fps / RGBA8888"}]
    assert metrics[0]["Subsystem"] == "camera"
    assert metrics[1]["Power"] == "85.5 mW"


def test_level0_resource_overview_formatter_exposes_endpoint_details():
    view = _view()

    assert sensor_summary_rows(view) == [
        {
            "Sensor": "sensor_rear",
            "Mode": "wide_video_16_9_30",
            "Module": "ip-sensor-rear-s5e9965",
            "Output": "4080x2296 @ 30fps / RAW10 / 10b",
            "Downstream": "csis",
        }
    ]
    assert display_summary_rows(view) == [
        {
            "Display": "dpu",
            "Composer": "DPU_DIRECT",
            "Layers": "3",
            "Panel Mode": "120hz",
            "Output": "1920x1080 @ 60fps / RGB888",
        }
    ]
    assert display_layer_rows(view) == [
        {
            "Display": "dpu",
            "Layer": "Camera Preview",
            "Buffer": "preview_buf",
            "Format": "NV12",
            "Src": "0,0 1920x1080",
            "Dst": "0,96 1080x1920",
            "Transform": "ROT_90",
        }
    ]


def test_pipeline_viewer_page_renders_level0_resource_overview_component():
    source = Path("dashboard/pages/2_Pipeline_Viewer.py").read_text(encoding="utf-8")

    assert "render_level0_resource_overview" in source
    assert source.index("render_level0_resource_overview") < source.index("Level 0 - Architecture View")


def test_level0_resource_overview_component_uses_vertical_table_layout():
    source = Path("dashboard/components/level0_resource_overview.py").read_text(encoding="utf-8")

    assert "st.columns" not in source
    assert source.index("resource_overview_rows") < source.index("metric_breakdown_rows")


def test_level0_resource_overview_styles_rows_by_subsystem():
    view = _view()
    rows = resource_overview_rows(view)

    camera_style = resource_overview_row_style(rows[0])
    display_style = resource_overview_row_style(rows[1])

    assert {"camera", "display", "video", "audio", "ai", "game", "compute"} <= set(SUBSYSTEM_ROW_COLORS)
    assert SUBSYSTEM_ROW_COLORS["camera"] in "".join(camera_style)
    assert SUBSYSTEM_ROW_COLORS["display"] in "".join(display_style)
    assert camera_style != display_style
    assert len(camera_style) == len(rows[0])


def test_level0_resource_overview_component_uses_styled_resource_table():
    source = Path("dashboard/components/level0_resource_overview.py").read_text(encoding="utf-8")

    assert "styled_resource_overview(resource_rows)" in source
