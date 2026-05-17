from __future__ import annotations

from types import SimpleNamespace

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.view.level0_v2 import build_resource_overview


def _ip(category: str):
    return SimpleNamespace(category=category, capabilities={}, hierarchy={})


def _graph(
    scenario_id: str,
    variant_id: str,
    nodes: list[dict],
    edges: list[dict],
    buffers: dict,
    design: dict,
    *,
    disabled_nodes: list[str] | None = None,
    disabled_edges: list[dict] | None = None,
    node_configs: dict | None = None,
):
    scenario = SimpleNamespace(
        id=scenario_id,
        project_ref="proj-sm-s947b",
        metadata_={"name": scenario_id.replace("-", " ").title(), "category": [scenario_id], "domain": [scenario_id]},
        pipeline={"nodes": nodes, "edges": edges, "buffers": buffers},
        size_profile={"anchors": {"record_out": "1920x1080", "preview_out": "1920x1080", "sensor_full": "4080x2296"}},
    )
    variant = SimpleNamespace(
        id=variant_id,
        severity="medium",
        design_conditions=design,
        routing_switch={"disabled_nodes": disabled_nodes or [], "disabled_edges": disabled_edges or []},
        topology_patch={},
        node_configs=node_configs or {},
        buffer_overrides={},
        ip_requirements={},
        sw_requirements={},
        resolved=True,
        inheritance_chain=[variant_id],
    )
    return CanonicalScenarioGraph(
        scenario=scenario,
        variant=variant,
        soc=SimpleNamespace(id="soc-exynos2600"),
        ip_catalog={
            "ip-cpu-s5e9965": _ip("cpu"),
            "ip-gpu-s5e9965": _ip("gpu"),
            "ip-npu-s5e9965": _ip("npu"),
            "ip-dpu-s5e9965": _ip("display"),
            "ip-display-panel-s5e9965": _ip("display"),
            "ip-mfc-s5e9965": _ip("codec"),
        },
    )


def test_game_npu_variant_rows_show_cpu_gpu_npu_dpu_panel_and_active_buffers():
    graph = _graph(
        "uc-game-play",
        "game-fhd-60fps-npu-ai",
        nodes=[
            {"id": "cpu", "ip_ref": "ip-cpu-s5e9965", "role": "cpu"},
            {"id": "gpu", "ip_ref": "ip-gpu-s5e9965", "role": "gpu_renderer"},
            {"id": "npu", "ip_ref": "ip-npu-s5e9965", "role": "npu"},
            {"id": "dpu", "ip_ref": "ip-dpu-s5e9965", "role": "display_controller"},
            {"id": "panel", "ip_ref": "ip-display-panel-s5e9965", "role": "display_output"},
        ],
        edges=[
            {"from": "cpu", "to": "gpu", "type": "control"},
            {"from": "gpu", "to": "npu", "type": "M2M", "buffer": "GPU_NPU_BUF"},
            {"from": "npu", "to": "dpu", "type": "M2M", "buffer": "NPU_DPU_BUF"},
            {"from": "dpu", "to": "panel", "type": "OTF"},
        ],
        buffers={
            "GPU_NPU_BUF": {"format": "RGBA8888", "bitdepth": 8, "compression": "COMP_OFF"},
            "NPU_DPU_BUF": {"format": "RGBA8888", "bitdepth": 8, "compression": "COMP_OFF"},
        },
        design={"resolution": "FHD", "target_fps": 60, "npu_used": True, "dpu_composer": "DPU_DIRECT", "dpu_layer_count": 5},
    )

    overview = build_resource_overview(graph)

    kinds = [row.resource_kind for row in overview.rows]
    assert kinds == ["cpu_task", "gpu", "npu", "dpu", "panel"]
    assert overview.rows[1].buffer_refs == ["GPU_NPU_BUF"]
    assert overview.rows[2].buffer_refs == ["NPU_DPU_BUF"]
    assert overview.displays[0].composer == "DPU_DIRECT"
    assert overview.displays[0].layer_count == 5


def test_youtube_gpu_fallback_keeps_gpu_path_and_hides_disabled_direct_dpu_path():
    graph = _graph(
        "uc-youtube-playback",
        "yt-1080p30-av1-gpu-overlay",
        nodes=[
            {"id": "network", "ip_ref": "ip-cpu-s5e9965", "role": "source"},
            {"id": "sw_demux", "ip_ref": "ip-cpu-s5e9965", "role": "demux"},
            {"id": "mfc_dec", "ip_ref": "ip-mfc-s5e9965", "role": "decoder"},
            {"id": "gpu", "ip_ref": "ip-gpu-s5e9965", "role": "composer"},
            {"id": "dpu", "ip_ref": "ip-dpu-s5e9965", "role": "display_controller"},
            {"id": "panel", "ip_ref": "ip-display-panel-s5e9965", "role": "display_output"},
        ],
        edges=[
            {"from": "network", "to": "sw_demux", "type": "control"},
            {"from": "sw_demux", "to": "mfc_dec", "type": "M2M", "buffer": "NET_ES_BUF"},
            {"from": "mfc_dec", "to": "dpu", "type": "M2M", "buffer": "MFC_DPU_BUF"},
            {"from": "mfc_dec", "to": "gpu", "type": "M2M", "buffer": "MFC_GPU_BUF"},
            {"from": "gpu", "to": "dpu", "type": "M2M", "buffer": "GPU_DPU_BUF"},
            {"from": "dpu", "to": "panel", "type": "OTF"},
        ],
        buffers={
            "NET_ES_BUF": {"format": "BITSTREAM", "compression": "COMP_OFF"},
            "MFC_DPU_BUF": {"format": "YUV420", "bitdepth": 8, "compression": "COMP_OFF"},
            "MFC_GPU_BUF": {"format": "YUV420", "bitdepth": 8, "compression": "COMP_OFF"},
            "GPU_DPU_BUF": {"format": "RGBA8888", "bitdepth": 8, "compression": "COMP_OFF"},
        },
        design={"resolution": "FHD", "fps": 30, "codec_mfc": "AV1_DEC", "dpu_composer": "GPU_FALLBACK", "dpu_layer_count": 14},
        disabled_edges=[{"from": "mfc_dec", "to": "dpu"}],
    )

    overview = build_resource_overview(graph)

    route_buffers = [buffer for row in overview.rows for buffer in row.buffer_refs]
    assert "MFC_DPU_BUF" not in route_buffers
    assert "MFC_GPU_BUF" in route_buffers
    assert "GPU_DPU_BUF" in route_buffers
    assert overview.displays[0].composer == "GPU_FALLBACK"
    assert any(row.resource_kind == "gpu" for row in overview.rows)


def test_camera_recording_summary_exposes_sensor_mode_and_display_composition():
    graph = _graph(
        "uc-camera-recording",
        "cam-rec-r1-fhd30-vdis",
        nodes=[
            {"id": "sensor_rear", "ip_ref": "ip-sensor-rear-s5e9965", "role": "sensor"},
            {"id": "csis", "ip_ref": "ip-csis-s5e9965", "role": "capture"},
            {"id": "dpu", "ip_ref": "ip-dpu-s5e9965", "role": "display_controller"},
            {"id": "panel", "ip_ref": "ip-display-panel-s5e9965", "role": "display_output"},
        ],
        edges=[
            {"from": "sensor_rear", "to": "csis", "type": "OTF"},
            {"from": "dpu", "to": "panel", "type": "OTF"},
        ],
        buffers={},
        design={
            "resolution": "FHD",
            "fps": 30,
            "dpu_composer": "DPU_DIRECT",
            "dpu_layer_count": 3,
            "panel_fps_hz": 120,
            "display_layers": [
                {
                    "name": "Camera Preview",
                    "buffer_ref": "preview_buf",
                    "format": "NV12",
                    "src_frame": "0,0 1920x1080",
                    "dst_frame": "0,96 1080x1920",
                    "transform": "ROT_90",
                }
            ],
        },
        node_configs={
            "sensor_rear": {
                "selected_mode": "wide_video_16_9_30",
                "outputs": [{"size": [0, 0, 4080, 2296], "format": "RAW10", "bitwidth": 10}],
            },
            "panel": {"selected_mode": "120hz"},
        },
    )
    graph.ip_catalog["ip-sensor-rear-s5e9965"] = _ip("sensor")
    graph.ip_catalog["ip-csis-s5e9965"] = _ip("camera")

    overview = build_resource_overview(graph)

    assert overview.sensors[0].sensor_mode == "wide_video_16_9_30"
    assert overview.sensors[0].output.width == 4080
    assert overview.sensors[0].output.height == 2296
    assert overview.sensors[0].output.fps == 30
    assert overview.sensors[0].output.format == "RAW10"
    assert overview.sensors[0].output.bitdepth == 10
    assert overview.sensors[0].downstream == ["csis"]
    assert overview.displays[0].composer == "DPU_DIRECT"
    assert overview.displays[0].layer_count == 3
    assert overview.displays[0].panel_mode == "120hz"
    assert overview.displays[0].layers[0].name == "Camera Preview"
    assert overview.displays[0].layers[0].buffer_ref == "preview_buf"
    assert overview.displays[0].layers[0].transform == "ROT_90"
