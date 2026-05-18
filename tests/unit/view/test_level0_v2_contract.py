from __future__ import annotations

from scenario_db.api.schemas.view import (
    BufferHandoffSummary,
    DisplayCompositionSummary,
    DisplayLayerSummary,
    IoSummary,
    Level0MetricBreakdown,
    Level0ResourceOverview,
    ResourceMetricSummary,
    ResourceOverviewRow,
    SensorEndpointSummary,
    ViewResponse,
    ViewSummary,
)


def test_view_response_accepts_level0_resource_overview_payload():
    overview = Level0ResourceOverview(
        rows=[
            ResourceOverviewRow(
                sequence_index=1,
                node_id="gpu",
                label="GPU",
                resource_domain="soc_resource",
                resource_kind="gpu",
                subsystem="display",
                role="composer",
                input=IoSummary(width=1920, height=1080, fps=60, format="RGBA8888", bitdepth=8),
                output=IoSummary(width=1920, height=1080, fps=60, format="RGBA8888", bitdepth=8),
                flow="M2M",
                buffer_refs=["GPU_DPU_BUF"],
                badges=["GPU", "M2M"],
                metrics=ResourceMetricSummary(power_mw=95.0, bw_total_mbs=1200.0, hw_time_ms=2.4),
                detail_items=["Composer: GPU_FALLBACK"],
            )
        ],
        buffers=[
            BufferHandoffSummary(
                buffer_ref="GPU_DPU_BUF",
                subsystem="display",
                producer_node_id="gpu",
                consumer_node_ids=["dpu"],
                size_label="1920x1080",
                format="RGBA8888",
                bitdepth=8,
                compression="COMP_OFF",
                comp_ratio=None,
                llc_allocated=True,
                llc_policy="dedicated",
                llc_allocation_mb=1.0,
            )
        ],
        metric_breakdown=[
            Level0MetricBreakdown(
                subsystem="display",
                power_mw=95.0,
                bw_total_mbs=1200.0,
                hw_time_ms=2.4,
                node_count=1,
            )
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
                composer="GPU_FALLBACK",
                layer_count=14,
                panel_mode="FHD+ 120Hz",
                output=IoSummary(width=1080, height=2340, fps=120, format="RGB"),
                layers=[
                    DisplayLayerSummary(
                        name="Camera Preview",
                        buffer_ref="preview_buf",
                        format="YUV420",
                        src_frame="0,0 1920x1080",
                        dst_frame="0,96 1080x1920",
                        transform="ROT_90",
                    )
                ],
            )
        ],
        notes=["Level0 v2 is resource-flow first."],
    )

    view = ViewResponse(
        level=0,
        mode="resource",
        scenario_id="uc-game-play",
        variant_id="game-fhd-60fps-npu-ai",
        nodes=[],
        edges=[],
        summary=ViewSummary(
            scenario_id="uc-game-play",
            variant_id="game-fhd-60fps-npu-ai",
            name="Game Play",
            subtitle="FHD 60fps",
            period_ms=16.67,
            budget_ms=16.67,
            resolution="FHD",
            fps=60,
            variant_label="game-fhd-60fps-npu-ai",
        ),
        level0_resource_overview=overview,
    )

    dumped = view.model_dump()
    assert dumped["level0_resource_overview"]["rows"][0]["resource_kind"] == "gpu"
    assert dumped["level0_resource_overview"]["rows"][0]["input_buffer_refs"] == []
    assert dumped["level0_resource_overview"]["buffers"][0]["consumer_node_ids"] == ["dpu"]
    assert dumped["level0_resource_overview"]["buffers"][0]["llc_allocated"] is True
    assert dumped["level0_resource_overview"]["sensors"][0]["output"]["format"] == "RAW10"
    assert dumped["level0_resource_overview"]["displays"][0]["layers"][0]["transform"] == "ROT_90"
