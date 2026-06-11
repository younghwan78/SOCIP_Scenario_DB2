from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import yaml

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.view import service
from scenario_db.view.level2_semantic import Level2NodeSpec, _level2_node_spec


FIXTURE_ROOT = Path("db_fixtures_Exynos2600_S26Plus")


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _deep_merge(base: dict, override: dict) -> dict:
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _resolve_variant(raw: dict, variant_id: str) -> dict:
    by_id = {str(item["id"]): item for item in raw.get("variants") or [] if item.get("id")}
    variant = by_id[variant_id]

    def _resolve(item: dict) -> dict:
        parent_id = item.get("derived_from_variant") or item.get("derived_from")
        if parent_id and parent_id in by_id:
            return _deep_merge(_resolve(by_id[parent_id]), item)
        return deepcopy(item)

    resolved = _resolve(variant)
    resolved["inheritance_chain"] = [variant_id]
    return resolved


def _catalog() -> dict[str, SimpleNamespace]:
    catalog: dict[str, SimpleNamespace] = {}
    for path in (FIXTURE_ROOT / "00_hw").glob("ip-*.yaml"):
        raw = _load_yaml(path)
        catalog[str(raw["id"])] = SimpleNamespace(
            category=raw.get("category"),
            capabilities=raw.get("capabilities") or {},
            hierarchy=raw.get("hierarchy") or {},
        )
    return catalog


def _graph(scenario_file: str, variant_id: str) -> CanonicalScenarioGraph:
    raw = _load_yaml(FIXTURE_ROOT / "02_definition" / scenario_file)
    variant = _resolve_variant(raw, variant_id)
    return CanonicalScenarioGraph(
        scenario=SimpleNamespace(
            id=raw["id"],
            project_ref=raw.get("project_ref"),
            metadata_=raw.get("metadata") or {},
            pipeline=raw.get("pipeline") or {},
            size_profile=raw.get("size_profile") or {},
        ),
        variant=SimpleNamespace(
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
            inheritance_chain=variant.get("inheritance_chain") or [variant["id"]],
        ),
        soc=SimpleNamespace(id="soc-exynos2600"),
        ip_catalog=_catalog(),
    )


def _node_by_id(view):
    return {node.data.id: node for node in view.nodes}


def test_level2_unavailable_when_ip_has_no_module_declarations():
    graph = _graph("uc-game-play.yaml", "game-fhd-60fps-npu-ai")

    view = service._project_drilldown(graph, "gpu")

    assert view.metadata["layout"] == "level2-unavailable"
    assert view.metadata["level2_available"] is False
    assert view.nodes == []
    assert view.edges == []
    assert "ip-gpu-s5e9965" in " ".join(view.metadata["unavailable_reasons"])
    assert "module" in " ".join(view.metadata["required_data"]).lower()


def test_level2_expands_declared_modules_for_single_active_camera_node():
    graph = _graph("uc-camera-recording.yaml", "cam-rec-3rdparty-binning")

    view = service._project_drilldown(graph, "csispdp")
    nodes = _node_by_id(view)

    assert view.metadata["layout"] == "level2-module-detail"
    assert view.metadata["level2_available"] is True
    assert nodes["l2pkg-csispdp"].data.hierarchy_group == "ISP"
    assert nodes["mod-csispdp-csispdp"].data.model_dump()["module_kind"] == "functional"
    assert nodes["mod-csispdp-csispdp-wdma"].data.model_dump()["module_kind"] == "wdma"
    assert nodes["mod-csispdp-csispdp-wdma"].data.model_dump()["module_direction"] == "output"
    assert nodes["buf-csispdp-3aa-buf"].data.memory.format == "RAW_BAYER_16"
    assert any(edge.data.buffer_ref == "CSISPDP_3AA_BUF" for edge in view.edges)


def test_level2_camera_expand_uses_active_graph_not_hardcoded_reference_nodes():
    graph = _graph("uc-camera-recording.yaml", "cam-rec-3rdparty-binning")

    view = service._project_drilldown(graph, "camera")
    node_ids = {node.data.id for node in view.nodes}

    assert view.metadata["layout"] == "level2-module-detail"
    assert "l2cam-mlsc" not in node_ids
    assert {"mod-csispdp-csispdp", "mod-byrp-byrp", "mod-yuvsc-yuvsc", "mod-mtnr-mtnr"} <= node_ids
    assert {"buf-yuvsc-mtnr-buf", "buf-csispdp-3aa-buf"} <= node_ids


def test_level2_node_spec_uses_typed_spec_object():
    graph = _graph("uc-camera-recording.yaml", "cam-rec-3rdparty-binning")
    node = next(item for item in graph.pipeline_nodes if item["id"] == "csispdp")

    spec, reason = _level2_node_spec(graph, node)

    assert reason == ""
    assert isinstance(spec, Level2NodeSpec)
    assert spec.node_id == "csispdp"
    assert spec.ip_ref == "ip-isp-s5e9965"


def test_level2_hierarchy_only_ip_derives_io_modules_from_m2m_edges():
    graph = CanonicalScenarioGraph(
        scenario=SimpleNamespace(
            id="uc-demo-import-recording",
            project_ref="proj-demo-import",
            metadata_={"name": "Demo Imported Camera Recording"},
            pipeline={
                "nodes": [
                    {"id": "isp0", "role": "main", "ip_ref": "ip-isp-v12"},
                    {"id": "mfc", "ip_ref": "ip-mfc-v14"},
                    {"id": "dpu", "ip_ref": "ip-dpu-v9"},
                ],
                "edges": [
                    {"from": "isp0", "to": "mfc", "type": "M2M", "buffer": "RECORD_BUF"},
                    {"from": "isp0", "to": "dpu", "type": "M2M", "buffer": "PREVIEW_BUF"},
                ],
                "buffers": {
                    "RECORD_BUF": {"format": "NV12"},
                    "PREVIEW_BUF": {"format": "NV12"},
                },
            },
            size_profile={},
        ),
        variant=SimpleNamespace(
            id="FHD30-Imported",
            severity="nominal",
            design_conditions={},
            size_overrides={},
            routing_switch={},
            topology_patch={},
            node_configs={},
            buffer_overrides={},
            ip_requirements={},
            sw_requirements={},
            resolved=True,
            inheritance_chain=["FHD30-Imported"],
        ),
        soc=SimpleNamespace(id="soc-exynos2500"),
        ip_catalog={
            "ip-isp-v12": SimpleNamespace(
                category="camera",
                capabilities={"properties": {}},
                hierarchy={
                    "type": "composite",
                    "submodules": [
                        {"ref": "sub-3aa-v4", "instance_id": "ISP.3AA0"},
                        {"ref": "sub-tnr-v3", "instance_id": "ISP.TNR"},
                    ],
                },
            ),
            "ip-mfc-v14": SimpleNamespace(category="codec", capabilities={}, hierarchy={}),
            "ip-dpu-v9": SimpleNamespace(category="display", capabilities={}, hierarchy={}),
        },
    )

    view = service._project_drilldown(graph, "isp0")
    nodes = _node_by_id(view)

    assert view.metadata["level2_available"] is True
    assert "scenario.pipeline.edges" in view.metadata["module_source"]
    assert nodes["mod-isp0-isp0-wdma"].data.module_kind == "wdma"
    assert nodes["mod-isp0-isp0-wdma"].data.module_direction == "output"
    assert nodes["mod-isp0-isp0-wdma"].data.module_status == "derived_from_pipeline_edge"
    assert any(edge.data.source == "mod-isp0-isp0-wdma" and edge.data.buffer_ref == "RECORD_BUF" for edge in view.edges)
    assert any(edge.data.source == "mod-isp0-isp0-wdma" and edge.data.buffer_ref == "PREVIEW_BUF" for edge in view.edges)
