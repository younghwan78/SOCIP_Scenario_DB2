from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.view.level0_v2 import build_resource_overview, project_level0_topology_view


FIXTURE_ROOT = Path("db_fixtures_Exynos2600_S26Plus")


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _ip_catalog() -> dict[str, SimpleNamespace]:
    catalog: dict[str, SimpleNamespace] = {}
    for path in (FIXTURE_ROOT / "00_hw").glob("ip-*.yaml"):
        raw = _load_yaml(path)
        catalog[str(raw["id"])] = SimpleNamespace(
            category=raw.get("category"),
            capabilities=raw.get("capabilities") or {},
            hierarchy=raw.get("hierarchy") or {},
        )
    return catalog


def _scenario_graph(file_name: str, variant_id: str) -> CanonicalScenarioGraph:
    raw = _load_yaml(FIXTURE_ROOT / "02_definition" / file_name)
    variant = next(item for item in raw["variants"] if item["id"] == variant_id)
    scenario = SimpleNamespace(
        id=raw["id"],
        project_ref=raw["project_ref"],
        metadata_=raw.get("metadata") or {},
        pipeline=raw.get("pipeline") or {},
        size_profile=raw.get("size_profile") or {"anchors": {"record_out": "1920x1080", "preview_out": "1920x1080"}},
    )
    resolved_variant = SimpleNamespace(
        id=variant["id"],
        severity=variant.get("severity"),
        design_conditions=variant.get("design_conditions") or {},
        size_overrides=variant.get("size_overrides") or {},
        routing_switch=variant.get("routing_switch") or {},
        topology_patch=variant.get("topology_patch") or {},
        node_configs=variant.get("node_configs") or {},
        buffer_overrides=variant.get("buffer_overrides") or {},
        ip_requirements=variant.get("ip_requirements") or {},
        sw_requirements=variant.get("sw_requirements") or {},
        resolved=True,
        inheritance_chain=[variant["id"]],
    )
    return CanonicalScenarioGraph(
        scenario=scenario,
        variant=resolved_variant,
        soc=SimpleNamespace(id="soc-exynos2600"),
        ip_catalog=_ip_catalog(),
    )


def _route_buffers(graph: CanonicalScenarioGraph) -> set[str]:
    overview = build_resource_overview(graph)
    return {buffer for row in overview.rows for buffer in row.buffer_refs}


def test_camera_recording_fixture_exposes_sensor_display_and_buffer_topology():
    graph = _scenario_graph("uc-camera-recording.yaml", "cam-rec-3rdparty-binning")

    overview = build_resource_overview(graph)
    topology = project_level0_topology_view(graph)
    topology_node_ids = {node.data.id for node in topology.nodes}

    assert overview.sensors[0].node_id == "sensor_rear"
    assert overview.sensors[0].sensor_mode == "binning_4x4"
    assert overview.displays[0].layer_count == 3
    assert "GDC_M_DPU_BUF" in _route_buffers(graph)
    assert "buf-gdc-m-dpu-buf" in topology_node_ids
    # Operation badges come only from explicit facts: n3aa declares none,
    # while yuvsc now declares its sensor->record downscale in the fixture.
    assert not any(node.data.active_operations for node in topology.nodes if node.data.id == "ip-n3aa")
    yuvsc_nodes = [node for node in topology.nodes if node.data.id == "ip-yuvsc"]
    assert yuvsc_nodes and yuvsc_nodes[0].data.active_operations is not None
    assert yuvsc_nodes[0].data.active_operations.scale is True
    assert yuvsc_nodes[0].data.active_operations.scale_to == "1920x1080"


def test_youtube_gpu_fallback_fixture_keeps_gpu_path_and_buffer_compression():
    graph = _scenario_graph("uc-youtube-playback.yaml", "yt-1080p30-av1-gpu-overlay")

    overview = build_resource_overview(graph)
    topology = project_level0_topology_view(graph)
    buffer_nodes = {node.data.id: node.data for node in topology.nodes if node.data.type == "buffer"}

    assert overview.displays[0].composer == "GPU_FALLBACK"
    assert "MFC_DPU_BUF" not in _route_buffers(graph)
    assert {"MFC_GPU_BUF", "GPU_DPU_BUF"} <= _route_buffers(graph)
    assert any(row.resource_kind == "gpu" for row in overview.rows)
    assert buffer_nodes["buf-gpu-dpu-buf"].memory.format == "RGBA8888"
    assert buffer_nodes["buf-gpu-dpu-buf"].memory.compression == "COMP_OFF"


def test_game_npu_fixture_uses_npu_route_and_hides_disabled_direct_gpu_dpu_route():
    graph = _scenario_graph("uc-game-play.yaml", "game-fhd-60fps-npu-ai")

    overview = build_resource_overview(graph)
    topology = project_level0_topology_view(graph)
    edge_pairs = {(edge.data.source, edge.data.target, edge.data.buffer_ref) for edge in topology.edges}

    assert {"gpu", "npu", "dpu", "panel"} <= {row.node_id for row in overview.rows}
    assert "GPU_DPU_BUF" not in _route_buffers(graph)
    assert {"GPU_NPU_BUF", "NPU_DPU_BUF"} <= _route_buffers(graph)
    assert ("ip-gpu", "buf-gpu-npu-buf", "GPU_NPU_BUF") in edge_pairs
    assert ("buf-npu-dpu-buf", "ip-dpu", "NPU_DPU_BUF") in edge_pairs


def test_audio_streaming_fixture_stays_audio_focused_without_camera_resources():
    graph = _scenario_graph("uc-audio-streaming.yaml", "audio-stream-aac-screen-on")

    overview = build_resource_overview(graph)
    topology = project_level0_topology_view(graph)
    node_ids = {row.node_id for row in overview.rows}
    kinds = {row.resource_kind for row in overview.rows}

    assert "sensor" not in kinds
    assert "dpu" not in kinds
    assert "audio" in kinds
    assert "speaker" in node_ids
    assert "bt_codec" not in node_ids
    assert "buf-stream-buf" in {node.data.id for node in topology.nodes}
