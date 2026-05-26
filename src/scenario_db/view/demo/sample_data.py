"""Hardcoded sample view payloads for dashboard fallback mode."""
from __future__ import annotations

from scenario_db.api.schemas.view import (
    EdgeData,
    EdgeElement,
    MemoryDescriptor,
    MemoryPlacement,
    NodeData,
    NodeElement,
    OperationSummary,
    RiskCard,
    ViewHints,
    ViewResponse,
    ViewSummary,
)
from scenario_db.view.layout import CANVAS_H, CANVAS_W, LANE_Y


def _n(
    nid: str,
    label: str,
    ntype: str,
    layer: str,
    x: float,
    y: float,
    **kwargs,
) -> NodeElement:
    data = NodeData(id=nid, label=label, type=ntype, layer=layer, **kwargs)
    return NodeElement(data=data, position={"x": x, "y": y})


def _e(eid: str, src: str, tgt: str, flow_type: str, **kwargs) -> EdgeElement:
    data = EdgeData(id=eid, source=src, target=tgt, flow_type=flow_type, **kwargs)
    return EdgeElement(data=data)


def build_sample_level0() -> ViewResponse:
    """Return a hardcoded Level 0 ViewResponse for the FHD30 demo scenario."""
    ly = LANE_Y

    nodes: list[NodeElement] = [
        _n("app-camera", "Camera App", "sw", "app", 210, ly["app"], view_hints=ViewHints(lane="app", stage="capture", order=0)),
        _n("app-recorder", "Recorder App", "sw", "app", 510, ly["app"], view_hints=ViewHints(lane="app", stage="processing", order=0)),
        _n("fw-cam-svc", "CameraService", "sw", "framework", 210, ly["framework"], view_hints=ViewHints(lane="framework", stage="capture", order=0)),
        _n("fw-media-rec", "MediaRecorder", "sw", "framework", 510, ly["framework"], view_hints=ViewHints(lane="framework", stage="processing", order=0)),
        _n("fw-codec-fw", "MediaCodec FW", "sw", "framework", 790, ly["framework"], view_hints=ViewHints(lane="framework", stage="encode", order=0)),
        _n("hal-camera", "Camera HAL", "sw", "hal", 210, ly["hal"], view_hints=ViewHints(lane="hal", stage="capture", order=0)),
        _n("hal-codec2", "Codec2 HAL", "sw", "hal", 510, ly["hal"], view_hints=ViewHints(lane="hal", stage="processing", order=0)),
        _n("ker-v4l2", "V4L2 Camera Driver", "sw", "kernel", 210, ly["kernel"], view_hints=ViewHints(lane="kernel", stage="capture", order=0)),
        _n("ker-mfc-drv", "MFC Driver", "sw", "kernel", 510, ly["kernel"], view_hints=ViewHints(lane="kernel", stage="processing", order=0)),
        _n("ker-ion", "ION / DMA-BUF", "sw", "kernel", 790, ly["kernel"], view_hints=ViewHints(lane="kernel", stage="encode", order=0)),
        _n("ker-drm", "DRM / KMS", "sw", "kernel", 1010, ly["kernel"], view_hints=ViewHints(lane="kernel", stage="display", order=0), warning=False),
        _n("hw-sensor", "Sensor", "ip", "hw", 130, ly["hw"], view_hints=ViewHints(lane="hw", stage="capture", order=0, emphasis="primary")),
        _n("hw-csis", "CSIS", "ip", "hw", 240, ly["hw"], view_hints=ViewHints(lane="hw", stage="capture", order=1)),
        _n(
            "hw-isp",
            "ISP",
            "ip",
            "hw",
            410,
            ly["hw"],
            ip_ref="ip-isp-v12",
            capability_badges=["CROP", "SCALE", "HDR10"],
            active_operations=OperationSummary(scale=True, scale_from="4000x3000", scale_to="1920x1080", crop=True, crop_ratio=0.9),
            view_hints=ViewHints(lane="hw", stage="processing", order=0, emphasis="primary"),
        ),
        _n("hw-mlsc", "MLSC", "ip", "hw", 530, ly["hw"], view_hints=ViewHints(lane="hw", stage="processing", order=1)),
        _n("hw-mcsc", "MCSC", "ip", "hw", 645, ly["hw"], view_hints=ViewHints(lane="hw", stage="processing", order=2)),
        _n(
            "hw-mfc",
            "MFC",
            "ip",
            "hw",
            810,
            ly["hw"],
            ip_ref="ip-mfc-v14",
            capability_badges=["H.265", "AV1"],
            matched_issues=["iss-LLC-thrashing-0221"],
            warning=True,
            view_hints=ViewHints(lane="hw", stage="encode", order=0, emphasis="risk"),
        ),
        _n("hw-dpu", "DPU", "ip", "hw", 1010, ly["hw"], ip_ref="ip-dpu-v9", view_hints=ViewHints(lane="hw", stage="display", order=0)),
        _n("buf-raw", "RAW Buffer", "buffer", "memory", 195, ly["memory"], memory=MemoryDescriptor(format="RAW10", bitdepth=10, planes=1, width=4000, height=3000, fps=30), view_hints=ViewHints(lane="memory", stage="capture", order=0)),
        _n("buf-yuv", "YUV Preview Buffer", "buffer", "memory", 415, ly["memory"], memory=MemoryDescriptor(format="NV12", bitdepth=8, planes=2, width=1920, height=1080, fps=30), view_hints=ViewHints(lane="memory", stage="processing", order=0)),
        _n(
            "buf-enc-in",
            "Encoder Input Buffer",
            "buffer",
            "memory",
            605,
            ly["memory"],
            memory=MemoryDescriptor(format="NV12", compression="SBWC_v4", width=1920, height=1080, fps=30),
            placement=MemoryPlacement(llc_allocated=True, llc_allocation_mb=1.0, llc_policy="dedicated", allocation_owner="MFC"),
            view_hints=ViewHints(lane="memory", stage="processing", order=1),
        ),
        _n("buf-enc-out", "Encoded Bitstream", "buffer", "memory", 815, ly["memory"], memory=MemoryDescriptor(format="H.265", fps=30), view_hints=ViewHints(lane="memory", stage="encode", order=0)),
        _n("buf-disp", "Display Buffer", "buffer", "memory", 1010, ly["memory"], memory=MemoryDescriptor(format="ARGB8888", width=1920, height=1080, fps=30), view_hints=ViewHints(lane="memory", stage="display", order=0)),
    ]

    edges: list[EdgeElement] = [
        _e("e-app-h", "app-camera", "app-recorder", "control"),
        _e("e-cap-app-fw", "app-camera", "fw-cam-svc", "control"),
        _e("e-cap-fw-hal", "fw-cam-svc", "hal-camera", "control"),
        _e("e-cap-hal-ker", "hal-camera", "ker-v4l2", "control"),
        _e("e-cap-ker-hw", "ker-v4l2", "hw-csis", "control"),
        _e("e-proc-app-fw", "app-recorder", "fw-media-rec", "control"),
        _e("e-proc-fw-hal", "fw-media-rec", "hal-codec2", "control"),
        _e("e-proc-hal-ker", "hal-codec2", "ker-mfc-drv", "control"),
        _e("e-proc-ker-hw", "ker-mfc-drv", "hw-mlsc", "control"),
        _e("e-hal-votf", "hal-camera", "hal-codec2", "vOTF"),
        _e("e-hal-votf-r", "hal-codec2", "hal-camera", "vOTF"),
        _e("e-ker-otf", "ker-v4l2", "ker-mfc-drv", "OTF"),
        _e("e-ker-m2m", "ker-mfc-drv", "ker-ion", "M2M"),
        _e("e-ker-sw", "ker-ion", "ker-drm", "control"),
        _e("e-hw-sen-csis", "hw-sensor", "hw-csis", "OTF"),
        _e("e-hw-csis-isp", "hw-csis", "hw-isp", "OTF"),
        _e("e-hw-isp-mlsc", "hw-isp", "hw-mlsc", "OTF"),
        _e("e-hw-mlsc-mcsc", "hw-mlsc", "hw-mcsc", "OTF"),
        _e("e-hw-mcsc-mfc", "hw-mcsc", "hw-mfc", "M2M"),
        _e("e-hw-mfc-dpu", "hw-mfc", "hw-dpu", "M2M"),
        _e("e-isp-buf-yuv", "hw-isp", "buf-yuv", "M2M"),
        _e("e-mfc-buf-out", "hw-mfc", "buf-enc-out", "M2M"),
        _e("e-dpu-buf-disp", "hw-dpu", "buf-disp", "M2M"),
        _e("e-buf-raw-yuv", "buf-raw", "buf-yuv", "vOTF"),
        _e("e-buf-yuv-ein", "buf-yuv", "buf-enc-in", "vOTF"),
        _e("e-buf-ein-eout", "buf-enc-in", "buf-enc-out", "vOTF"),
        _e("e-risk-mfc", "hw-mfc", "ker-mfc-drv", "risk", label="Latency > budget"),
    ]

    summary = ViewSummary(
        scenario_id="uc-camera-recording",
        variant_id="FHD30-SDR-H265",
        name="Video Recording",
        subtitle="FHD 30fps, 1920x1080",
        period_ms=33.3,
        budget_ms=30.0,
        resolution="1920 x 1080",
        fps=30,
        variant_label="Samsung Exynos",
        notes="Scenario captured on Exynos reference board. Measurements via SurfaceFlinger and systrace.",
        captured_at="May 16, 2025 10:42 AM",
    )
    risks = [
        RiskCard(
            id="R1",
            title="MFC Encode Latency High",
            component="MFC",
            description="Encode latency 28.6 ms exceeds budget 30.0 ms (95th percentile)",
            severity="High",
            impact="Budget Overrun",
        ),
        RiskCard(
            id="R2",
            title="DRAM Bandwidth High",
            component="MFC / Memory",
            description="Peak bandwidth 18.2 GB/s near sustained limit 20.0 GB/s",
            severity="Medium",
            impact="Throughput Risk",
        ),
    ]
    return ViewResponse(
        level=0,
        mode="architecture",
        scenario_id="uc-camera-recording",
        variant_id="FHD30-SDR-H265",
        nodes=nodes,
        edges=edges,
        risks=risks,
        summary=summary,
        metadata={"canvas_w": CANVAS_W, "canvas_h": CANVAS_H},
        overlays_available=["issues", "memory-path", "llc-allocation", "compression"],
    )
