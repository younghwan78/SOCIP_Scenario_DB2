from __future__ import annotations

from types import SimpleNamespace

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.view.service import _project_architecture, _project_topology


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
                "GPU_NPU_BUF": {"format": "RGBA8888", "bitdepth": 8},
                "NPU_DPU_BUF": {"format": "RGBA8888", "bitdepth": 8},
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


def test_level0_architecture_response_embeds_resource_overview():
    view = _project_architecture(_graph(), level=0)

    assert view.level0_resource_overview is not None
    assert [row.resource_kind for row in view.level0_resource_overview.rows] == ["cpu_task", "gpu", "npu", "dpu", "panel"]
    assert view.level0_resource_overview.displays[0].composer == "DPU_DIRECT"


def test_level0_topology_response_embeds_same_resource_overview_contract():
    view = _project_topology(_graph(), level=0)

    assert view.level0_resource_overview is not None
    assert "GPU_NPU_BUF" in {
        buffer_ref
        for row in view.level0_resource_overview.rows
        for buffer_ref in row.buffer_refs
    }
