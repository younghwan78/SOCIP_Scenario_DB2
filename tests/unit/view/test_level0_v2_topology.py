from __future__ import annotations

from types import SimpleNamespace

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.view.level0_v2 import build_resource_overview
from scenario_db.view import service


def _ip(category: str):
    return SimpleNamespace(category=category, capabilities={}, hierarchy={})


def _graph() -> CanonicalScenarioGraph:
    scenario = SimpleNamespace(
        id="uc-game-play",
        project_ref="proj-sm-s947b",
        metadata_={"name": "Game Play", "category": ["game"], "domain": ["game"]},
        pipeline={
            "nodes": [
                {"id": "cpu", "ip_ref": "ip-cpu-s5e9965", "role": "cpu"},
                {"id": "gpu", "ip_ref": "ip-gpu-s5e9965", "role": "gpu_renderer"},
                {"id": "npu", "ip_ref": "ip-npu-s5e9965", "role": "npu"},
                {"id": "dpu", "ip_ref": "ip-dpu-s5e9965", "role": "display_controller"},
                {"id": "panel", "ip_ref": "ip-display-panel-s5e9965", "role": "display_output"},
            ],
            "edges": [
                {"from": "cpu", "to": "gpu", "type": "control"},
                {"from": "gpu", "to": "npu", "type": "M2M", "buffer": "GPU_NPU_BUF"},
                {"from": "npu", "to": "dpu", "type": "M2M", "buffer": "NPU_DPU_BUF"},
                {"from": "dpu", "to": "panel", "type": "OTF"},
            ],
            "buffers": {
                "GPU_NPU_BUF": {"format": "RGBA8888", "bitdepth": 8, "size": "1920x1080", "compression": "COMP_OFF"},
                "NPU_DPU_BUF": {"format": "RGBA8888", "bitdepth": 8, "size": "1920x1080", "compression": "COMP_OFF"},
            },
        },
        size_profile={"anchors": {"record_out": "1920x1080"}},
    )
    variant = SimpleNamespace(
        id="game-fhd-60fps-npu-ai",
        severity="medium",
        design_conditions={"resolution": "FHD", "target_fps": 60, "npu_used": True, "dpu_composer": "DPU_DIRECT"},
        size_overrides={},
        routing_switch={},
        topology_patch={},
        node_configs={},
        buffer_overrides={},
        ip_requirements={},
        sw_requirements={},
        resolved=True,
        inheritance_chain=["game-fhd-60fps-npu-ai"],
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
        },
    )


def _llc_graph() -> CanonicalScenarioGraph:
    graph = _graph()
    graph.scenario.pipeline["nodes"].append({"id": "llc", "ip_ref": "ip-llc-s5e9965", "role": "memory"})
    graph.scenario.pipeline["edges"] = [
        {"from": "gpu", "to": "llc", "type": "M2M", "buffer": "GPU_NPU_BUF"},
        {"from": "llc", "to": "npu", "type": "M2M", "buffer": "GPU_NPU_BUF"},
        {"from": "npu", "to": "dpu", "type": "M2M", "buffer": "NPU_DPU_BUF"},
        {"from": "dpu", "to": "panel", "type": "OTF"},
    ]
    graph.scenario.pipeline["buffers"]["GPU_NPU_BUF"]["placement"] = {
        "llc_allocated": True,
        "llc_policy": "dedicated",
        "llc_allocation_mb": 1.0,
    }
    graph.ip_catalog["ip-llc-s5e9965"] = _ip("memory")
    return graph


def test_project_level0_resource_mode_returns_resource_dashboard_payload(monkeypatch):
    graph = _graph()
    monkeypatch.setattr(service, "_load_graph", lambda db, scenario_id, variant_id: graph)

    view = service.project_level0("uc-game-play", "game-fhd-60fps-npu-ai", db=object(), mode="resource")

    assert view.mode == "resource"
    assert view.metadata["layout"] == "level0-resource-overview"
    assert view.metadata["active_node_count"] == 5
    assert view.metadata["active_edge_count"] == 4
    assert view.nodes == []
    assert view.edges == []
    assert [row.resource_kind for row in view.level0_resource_overview.rows] == ["cpu_task", "gpu", "npu", "dpu", "panel"]


def test_project_level0_topology_mode_projects_active_nodes_buffers_and_split_edges(monkeypatch):
    graph = _graph()
    monkeypatch.setattr(service, "_load_graph", lambda db, scenario_id, variant_id: graph)

    view = service.project_level0("uc-game-play", "game-fhd-60fps-npu-ai", db=object(), mode="topology")

    node_by_id = {node.data.id: node for node in view.nodes}
    edge_pairs = {(edge.data.source, edge.data.target, edge.data.buffer_ref) for edge in view.edges}

    assert view.mode == "topology"
    assert view.metadata["layout"] == "level0-resource-topology"
    assert view.metadata["active_node_count"] == 5
    assert view.metadata["active_edge_count"] == 4
    assert {"ip-cpu", "ip-gpu", "ip-npu", "ip-dpu", "ip-panel"} <= set(node_by_id)
    assert {"buf-gpu-npu-buf", "buf-npu-dpu-buf"} <= set(node_by_id)
    assert node_by_id["buf-gpu-npu-buf"].data.memory.format == "RGBA8888"
    assert node_by_id["buf-gpu-npu-buf"].data.memory.width == 1920
    assert node_by_id["buf-gpu-npu-buf"].data.memory.height == 1080
    assert ("ip-gpu", "buf-gpu-npu-buf", "GPU_NPU_BUF") in edge_pairs
    assert ("buf-gpu-npu-buf", "ip-npu", "GPU_NPU_BUF") in edge_pairs
    assert ("ip-npu", "buf-npu-dpu-buf", "NPU_DPU_BUF") in edge_pairs
    assert ("buf-npu-dpu-buf", "ip-dpu", "NPU_DPU_BUF") in edge_pairs


def test_level0_topology_collapses_llc_memory_node_into_buffer_placement(monkeypatch):
    graph = _llc_graph()
    monkeypatch.setattr(service, "_load_graph", lambda db, scenario_id, variant_id: graph)

    view = service.project_level0("uc-game-play", "game-fhd-60fps-npu-ai", db=object(), mode="topology")

    node_by_id = {node.data.id: node for node in view.nodes}
    edge_pairs = {(edge.data.source, edge.data.target, edge.data.buffer_ref) for edge in view.edges}

    assert "ip-llc" not in node_by_id
    assert view.metadata["active_node_count"] == 5
    assert view.metadata["active_edge_count"] == 3
    assert "buf-gpu-npu-buf" in node_by_id
    assert node_by_id["buf-gpu-npu-buf"].data.placement.llc_allocated is True
    assert "LLC" in node_by_id["buf-gpu-npu-buf"].data.summary_badges
    assert ("ip-gpu", "buf-gpu-npu-buf", "GPU_NPU_BUF") in edge_pairs
    assert ("buf-gpu-npu-buf", "ip-npu", "GPU_NPU_BUF") in edge_pairs


def test_buffer_handoff_size_falls_back_to_variant_resolution_when_spec_has_no_size():
    graph = _graph()
    graph.scenario.size_profile = {}
    graph.scenario.pipeline["buffers"]["GPU_NPU_BUF"].pop("size")
    graph.variant.design_conditions["resolution"] = "FHD"

    overview = build_resource_overview(graph)
    handoffs = {buffer.buffer_ref: buffer for buffer in overview.buffers}

    assert handoffs["GPU_NPU_BUF"].size_label == "1920x1080"


def test_topology_operation_badges_require_explicit_operation_facts(monkeypatch):
    graph = _graph()
    graph.scenario.pipeline["nodes"].append({"id": "yuvsc", "ip_ref": "ip-isp-s5e9965", "role": "yuv_scaler"})
    graph.scenario.pipeline["edges"].append({"from": "cpu", "to": "yuvsc", "type": "OTF"})
    graph.ip_catalog["ip-isp-s5e9965"] = _ip("camera")
    monkeypatch.setattr(service, "_load_graph", lambda db, scenario_id, variant_id: graph)

    view = service.project_level0("uc-game-play", "game-fhd-60fps-npu-ai", db=object(), mode="topology")

    node_by_id = {node.data.id: node for node in view.nodes}

    assert node_by_id["ip-yuvsc"].data.active_operations is None
    assert "Scale" not in node_by_id["ip-yuvsc"].data.summary_badges


def test_topology_operation_badges_show_explicit_crop_scale(monkeypatch):
    graph = _graph()
    graph.variant.node_configs["gpu"] = {
        "operations": {
            "crop": True,
            "scale": True,
            "scale_from": "4000x2250",
            "scale_to": "1920x1080",
        }
    }
    monkeypatch.setattr(service, "_load_graph", lambda db, scenario_id, variant_id: graph)

    view = service.project_level0("uc-game-play", "game-fhd-60fps-npu-ai", db=object(), mode="topology")

    node_by_id = {node.data.id: node for node in view.nodes}

    assert node_by_id["ip-gpu"].data.active_operations is not None
    assert node_by_id["ip-gpu"].data.summary_badges[-2:] == ["Crop", "Scale"]
