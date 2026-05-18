from __future__ import annotations

from scenario_db.api.schemas.view import (
    Level0ResourceOverview,
    ResourceOverviewRow,
    SensorEndpointSummary,
    IoSummary,
    ViewResponse,
    ViewSummary,
)
from dashboard.components.level0_detail_panel import scenario_context_description, scenario_context_rows


def _summary(*, name: str = "Audio Streaming", resolution: str = "unknown") -> ViewSummary:
    return ViewSummary(
        scenario_id="uc-audio-streaming",
        variant_id="audio-stream-aac-screen-on",
        name=name,
        subtitle="30fps",
        period_ms=33.33,
        budget_ms=30.0,
        resolution=resolution,
        fps=30,
        variant_label="soc-exynos2600",
    )


def test_audio_only_context_hides_video_frame_timing_defaults():
    view = ViewResponse(
        level=0,
        mode="resource",
        scenario_id="uc-audio-streaming",
        variant_id="audio-stream-aac-screen-on",
        nodes=[],
        edges=[],
        summary=_summary(),
        level0_resource_overview=Level0ResourceOverview(
            rows=[
                ResourceOverviewRow(
                    sequence_index=1,
                    node_id="speaker",
                    label="Speaker",
                    resource_domain="external_sink",
                    resource_kind="audio",
                    subsystem="audio",
                )
            ]
        ),
    )

    labels = [label for label, _ in scenario_context_rows(view)]

    assert "Scenario" in labels
    assert "Variant" in labels
    assert "Frame Rate" not in labels
    assert "Period" not in labels
    assert "Budget" not in labels
    assert "Resolution" not in labels
    assert "selected scenario resources" in scenario_context_description(view)


def test_camera_context_keeps_frame_timing_when_sensor_endpoint_exists():
    view = ViewResponse(
        level=0,
        mode="resource",
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-r1-fhd30",
        nodes=[],
        edges=[],
        summary=_summary(name="Camera Recording", resolution="1920 x 1080"),
        level0_resource_overview=Level0ResourceOverview(
            rows=[
                ResourceOverviewRow(
                    sequence_index=1,
                    node_id="sensor_rear",
                    label="Rear Sensor",
                    resource_domain="external_source",
                    resource_kind="sensor",
                    subsystem="camera",
                )
            ],
            sensors=[
                SensorEndpointSummary(
                    node_id="sensor_rear",
                    output=IoSummary(width=4080, height=2296, fps=30, format="RAW10"),
                )
            ],
        ),
    )

    labels = [label for label, _ in scenario_context_rows(view)]

    assert "Resolution" in labels
    assert "Frame Rate" in labels
    assert "Period" in labels
    assert "Budget" in labels
