from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import yaml

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.view import service


FIXTURE_ROOT = Path("db_fixtures_Exynos2600_S26Plus")
_EXYNOS_IP_CATALOG: dict[str, SimpleNamespace] | None = None


def _ip(category: str, *, properties: dict | None = None, role_modes: dict | None = None):
    capabilities = {"properties": properties or {}}
    if role_modes:
        capabilities["sim"] = {"role_modes": role_modes}
    return SimpleNamespace(category=category, capabilities=capabilities, hierarchy={})


def _role_mode(hw_name: str, dvfs_group: str):
    return {
        "hw_name": hw_name,
        "modes": {
            "Normal": {
                "dvfs_group": dvfs_group,
            }
        },
    }


def _graph() -> CanonicalScenarioGraph:
    scenario = SimpleNamespace(
        id="uc-camera-recording",
        project_ref="proj-sm-s947b",
        metadata_={"name": "Camera Recording", "category": ["camera"], "domain": ["camera"]},
        pipeline={
            "nodes": [
                {"id": "rear_sensor", "ip_ref": "ip-sensor-rear-s5e9965", "role": "sensor"},
                {"id": "csispdp", "ip_ref": "ip-isp-s5e9965", "role": "csispdp"},
                {"id": "n3aa", "ip_ref": "ip-isp-s5e9965", "role": "stats_3aa"},
                {"id": "byrp", "ip_ref": "ip-isp-s5e9965", "role": "bayer_processing"},
                {"id": "rgbp", "ip_ref": "ip-isp-s5e9965", "role": "rgb_processing"},
                {"id": "yuvsc", "ip_ref": "ip-isp-s5e9965", "role": "yuv_scaler"},
                {"id": "mtnr", "ip_ref": "ip-isp-s5e9965", "role": "temporal_nr"},
                {"id": "msnr", "ip_ref": "ip-isp-s5e9965", "role": "spatial_nr"},
                {"id": "yuvp", "ip_ref": "ip-isp-s5e9965", "role": "yuv_post"},
                {"id": "mcsc", "ip_ref": "ip-mcsc-s5e9965", "role": "mcsc"},
                {"id": "gdc_video", "ip_ref": "ip-isp-s5e9965", "role": "gdc_video"},
                {"id": "mfc_enc", "ip_ref": "ip-mfc-s5e9965", "role": "encoder"},
                {"id": "dpu", "ip_ref": "ip-dpu-s5e9965", "role": "display_controller"},
                {"id": "panel", "ip_ref": "ip-display-panel-s5e9965", "role": "display_output"},
            ],
            "edges": [
                {"from": "rear_sensor", "to": "csispdp", "type": "OTF"},
                {"from": "csispdp", "to": "byrp", "type": "OTF"},
                {"from": "csispdp", "to": "n3aa", "type": "M2M", "buffer": "CSISPDP_3AA_BUF"},
                {"from": "byrp", "to": "rgbp", "type": "OTF"},
                {"from": "rgbp", "to": "yuvsc", "type": "OTF"},
                {"from": "yuvsc", "to": "mtnr", "type": "M2M", "buffer": "YUVSC_MTNR_BUF"},
                {"from": "mtnr", "to": "msnr", "type": "OTF"},
                {"from": "msnr", "to": "yuvp", "type": "OTF"},
                {"from": "yuvp", "to": "mcsc", "type": "OTF"},
                {"from": "mcsc", "to": "gdc_video", "type": "M2M", "buffer": "MCSC_VIDEO_BUF"},
                {"from": "gdc_video", "to": "mfc_enc", "type": "M2M", "buffer": "GDC_MFC_BUF"},
                {"from": "gdc_video", "to": "dpu", "type": "M2M", "buffer": "GDC_DPU_BUF"},
                {"from": "dpu", "to": "panel", "type": "OTF"},
            ],
            "buffers": {
                "CSISPDP_3AA_BUF": {"format": "RAW_BAYER_16", "bitdepth": 12, "size": "4000x2250"},
                "YUVSC_MTNR_BUF": {"format": "YUV422", "bitdepth": 10, "size": "4000x2250", "compression": "COMP_OFF"},
                "MCSC_VIDEO_BUF": {"format": "YUV420", "bitdepth": 10, "size": "1920x1080"},
                "GDC_MFC_BUF": {"format": "YUV420", "bitdepth": 10, "size": "1920x1080"},
                "GDC_DPU_BUF": {"format": "RGBA8888", "bitdepth": 8, "size": "1920x1080"},
            },
        },
        size_profile={"anchors": {"sensor_full": "4000x2250", "record_out": "1920x1080"}},
    )
    variant = SimpleNamespace(
        id="cam-rec-3rdparty-binning",
        severity="heavy",
        design_conditions={"resolution": "FHD", "fps": 30, "codec": "H.265"},
        size_overrides={},
        routing_switch={},
        topology_patch={},
        node_configs={},
        buffer_overrides={},
        ip_requirements={},
        sw_requirements={},
        resolved=True,
        inheritance_chain=["cam-rec-3rdparty-binning"],
    )
    isp_role_modes = {
        "csispdp": _role_mode("PDP", "CSIS"),
        "stats_3aa": _role_mode("CSTAT", "CSIS"),
        "bayer_processing": _role_mode("BYRP", "CAM"),
        "rgb_processing": _role_mode("RGBP", "CAM"),
        "yuv_scaler": _role_mode("YUVSC", "CAM"),
        "temporal_nr": _role_mode("MTNR0", "INTCAM"),
        "spatial_nr": _role_mode("MSNR", "INTCAM"),
        "yuv_post": _role_mode("YUVP", "CAM"),
        "gdc_video": _role_mode("MCSC", "CAM"),
    }
    return CanonicalScenarioGraph(
        scenario=scenario,
        variant=variant,
        soc=SimpleNamespace(id="soc-exynos2600"),
        ip_catalog={
            "ip-sensor-rear-s5e9965": _ip("sensor", properties={"hierarchy_group": "Sensor", "ip_group": "Sensor"}),
            "ip-isp-s5e9965": _ip(
                "camera",
                properties={"hierarchy_group": "ISP", "ip_group": "ISP"},
                role_modes=isp_role_modes,
            ),
            "ip-mcsc-s5e9965": _ip("camera", properties={"hierarchy_group": "ISP", "ip_group": "MCSC"}),
            "ip-mfc-s5e9965": _ip("codec", properties={"hierarchy_group": "CODEC", "ip_group": "MFC"}),
            "ip-dpu-s5e9965": _ip("display", properties={"hierarchy_group": "DPU", "ip_group": "DPU"}),
            "ip-display-panel-s5e9965": _ip("display", properties={"hierarchy_group": "Display", "ip_group": "Panel"}),
        },
    )


def _semantic_graph(
    *,
    pipeline: dict,
    ip_catalog: dict[str, SimpleNamespace],
    node_configs: dict | None = None,
) -> CanonicalScenarioGraph:
    return CanonicalScenarioGraph(
        scenario=SimpleNamespace(
            id="uc-level1-semantic",
            project_ref="proj-sm-s947b",
            metadata_={"name": "Level1 Semantic"},
            pipeline=pipeline,
            size_profile={},
        ),
        variant=SimpleNamespace(
            id="semantic-variant",
            severity="light",
            design_conditions={},
            size_overrides={},
            routing_switch={},
            topology_patch={},
            node_configs=node_configs or {},
            buffer_overrides={},
            ip_requirements={},
            sw_requirements={},
            resolved=True,
            inheritance_chain=["semantic-variant"],
        ),
        soc=SimpleNamespace(id="soc-exynos2600"),
        ip_catalog=ip_catalog,
    )


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


def _resolve_fixture_variant(raw: dict, variant: dict) -> dict:
    by_id = {str(item["id"]): item for item in raw.get("variants") or [] if item.get("id")}

    def _resolve(item: dict) -> dict:
        parent_id = item.get("derived_from_variant") or item.get("derived_from")
        if parent_id and parent_id in by_id:
            return _deep_merge(_resolve(by_id[parent_id]), item)
        return deepcopy(item)

    resolved = _resolve(variant)
    resolved["inheritance_chain"] = [resolved["id"]]
    return resolved


def _exynos_ip_catalog() -> dict[str, SimpleNamespace]:
    global _EXYNOS_IP_CATALOG
    if _EXYNOS_IP_CATALOG is not None:
        return _EXYNOS_IP_CATALOG
    catalog: dict[str, SimpleNamespace] = {}
    for path in (FIXTURE_ROOT / "00_hw").glob("ip-*.yaml"):
        ip = _load_yaml(path)
        catalog[str(ip["id"])] = SimpleNamespace(
            category=ip.get("category"),
            capabilities=ip.get("capabilities") or {},
            hierarchy=ip.get("hierarchy") or {},
        )
    _EXYNOS_IP_CATALOG = catalog
    return catalog


def _exynos_fixture_graph() -> CanonicalScenarioGraph:
    raw = _load_yaml(FIXTURE_ROOT / "02_definition" / "uc-camera-recording.yaml")
    variant = next(item for item in raw["variants"] if item["id"] == "cam-rec-3rdparty-binning")
    return _exynos_fixture_graph_for(raw, variant)


def _exynos_fixture_graph_for(raw: dict, variant: dict) -> CanonicalScenarioGraph:
    resolved = _resolve_fixture_variant(raw, variant)
    return CanonicalScenarioGraph(
        scenario=SimpleNamespace(
            id=raw["id"],
            project_ref=raw["project_ref"],
            metadata_=raw.get("metadata") or {},
            pipeline=raw.get("pipeline") or {},
            size_profile=raw.get("size_profile") or {},
        ),
        variant=SimpleNamespace(
            id=resolved["id"],
            severity=resolved.get("severity"),
            design_conditions=resolved.get("design_conditions") or {},
            size_overrides=resolved.get("size_overrides") or {},
            routing_switch=resolved.get("routing_switch") or {},
            topology_patch=resolved.get("topology_patch") or {},
            node_configs=resolved.get("node_configs") or {},
            buffer_overrides=resolved.get("buffer_overrides") or {},
            ip_requirements=resolved.get("ip_requirements") or {},
            sw_requirements=resolved.get("sw_requirements") or {},
            resolved=True,
            inheritance_chain=resolved.get("inheritance_chain") or [resolved["id"]],
        ),
        soc=SimpleNamespace(id="soc-exynos2600"),
        ip_catalog=_exynos_ip_catalog(),
    )


def test_level1_uses_active_pipeline_nodes_with_isp_block_groups(monkeypatch):
    graph = _graph()
    monkeypatch.setattr(service, "_load_graph", lambda db, scenario_id, variant_id: graph)

    view = service.project_level1("uc-camera-recording", "cam-rec-3rdparty-binning", db=object())
    node_by_id = {node.data.id: node for node in view.nodes}

    assert view.metadata["layout"] == "level1-semantic-ip-dag"
    assert {"grp-isp", "grp-isp-csis-pdp", "grp-isp-3aa-cstat", "grp-isp-byrp", "grp-isp-mtnr"} <= set(node_by_id)
    assert {"ip-csispdp", "ip-n3aa", "ip-byrp", "ip-yuvsc", "ip-mtnr", "ip-mcsc", "ip-gdc-video"} <= set(node_by_id)
    assert "t_mlsc" not in node_by_id

    assert node_by_id["grp-isp-byrp"].data.parent == "grp-isp"
    assert node_by_id["ip-byrp"].data.parent == "grp-isp-byrp"
    assert node_by_id["ip-n3aa"].data.label == "N3AA"
    assert node_by_id["ip-n3aa"].data.hierarchy_group == "ISP"
    assert node_by_id["ip-n3aa"].data.ip_group == "3AA/CSTAT"
    assert node_by_id["ip-n3aa"].data.role_hw_name == "CSTAT"
    assert node_by_id["ip-mtnr"].data.dvfs_group == "INTCAM"
    assert node_by_id["ip-yuvsc"].data.active_operations is None

    yuvsc_mtnr = next(edge for edge in view.edges if edge.data.buffer_ref == "YUVSC_MTNR_BUF")
    assert yuvsc_mtnr.data.source == "ip-yuvsc"
    assert yuvsc_mtnr.data.target == "ip-mtnr"
    assert yuvsc_mtnr.data.memory.format == "YUV422"


def test_level1_operation_badges_require_explicit_operation_facts(monkeypatch):
    graph = _graph()
    graph.variant.node_configs["gdc_video"] = {
        "operations": {
            "scale": True,
            "scale_from": "1920x1080",
            "scale_to": "1280x720",
            "rotate": 90,
        }
    }
    monkeypatch.setattr(service, "_load_graph", lambda db, scenario_id, variant_id: graph)

    view = service.project_level1("uc-camera-recording", "cam-rec-3rdparty-binning", db=object())
    gdc = next(node for node in view.nodes if node.data.id == "ip-gdc-video")

    assert gdc.data.active_operations.scale is True
    assert gdc.data.active_operations.rotate == 90
    assert gdc.data.summary_badges[-2:] == ["Scale", "Rotate"]


def test_level1_exynos_fixture_keeps_display_panel_outside_isp_and_groups_gdc_separately():
    view = service._project_semantic_level1(_exynos_fixture_graph())
    node_by_id = {node.data.id: node for node in view.nodes}

    assert node_by_id["ip-panel"].data.hierarchy_group == "Display"
    assert node_by_id["ip-panel"].data.parent == "grp-display-panel"
    assert node_by_id["ip-gdc-m"].data.ip_group == "GDC"
    assert node_by_id["ip-gdc-o"].data.parent == "grp-isp-gdc"
    assert node_by_id["ip-mfc-enc"].data.hierarchy_group == "CODEC"


def test_level1_cpu_audio_decoder_stays_cpu_sw_not_mfc():
    graph = _semantic_graph(
        pipeline={
            "nodes": [
                {"id": "storage", "ip_ref": "ip-cpu-s5e9965", "role": "source"},
                {"id": "sw_decoder", "ip_ref": "ip-cpu-s5e9965", "role": "audio_decode"},
                {"id": "audio_hal", "ip_ref": "ip-cpu-s5e9965", "role": "audio_hal"},
            ],
            "edges": [
                {"from": "storage", "to": "sw_decoder", "type": "M2M", "buffer": "AUDIO_ES_BUF"},
                {"from": "sw_decoder", "to": "audio_hal", "type": "control"},
            ],
            "buffers": {"AUDIO_ES_BUF": {"format": "AUDIO_PCM", "bitdepth": 16}},
        },
        ip_catalog={"ip-cpu-s5e9965": _ip("cpu")},
    )

    view = service._project_semantic_level1(graph)
    node_by_id = {node.data.id: node for node in view.nodes}

    assert node_by_id["ip-sw-decoder"].data.hierarchy_group == "CPU/SW"
    assert node_by_id["ip-sw-decoder"].data.ip_group == "CPU/SW"
    assert node_by_id["ip-sw-decoder"].data.parent == "grp-cpu-sw-cpu-sw"
    assert "grp-codec-mfc" not in node_by_id


def test_level1_apv_decoder_uses_apv_block_not_mfc():
    graph = _semantic_graph(
        pipeline={
            "nodes": [
                {"id": "storage", "ip_ref": "ip-cpu-s5e9965", "role": "source"},
                {"id": "apv_dec", "ip_ref": "ip-apv-s5e9965", "role": "decoder"},
                {"id": "dpu", "ip_ref": "ip-dpu-s5e9965", "role": "display_controller"},
            ],
            "edges": [
                {"from": "storage", "to": "apv_dec", "type": "M2M", "buffer": "APV_ES_BUF"},
                {"from": "apv_dec", "to": "dpu", "type": "M2M", "buffer": "APV_DPU_BUF"},
            ],
        },
        ip_catalog={
            "ip-cpu-s5e9965": _ip("cpu"),
            "ip-apv-s5e9965": _ip("codec", properties={"hierarchy_group": "CODEC", "ip_group": "APV"}),
            "ip-dpu-s5e9965": _ip("display", properties={"hierarchy_group": "DPU", "ip_group": "DPU"}),
        },
    )

    view = service._project_semantic_level1(graph)
    node_by_id = {node.data.id: node for node in view.nodes}

    assert node_by_id["ip-apv-dec"].data.hierarchy_group == "CODEC"
    assert node_by_id["ip-apv-dec"].data.ip_group == "APV"
    assert node_by_id["ip-apv-dec"].data.parent == "grp-codec-apv"
    assert "grp-codec-mfc" not in node_by_id


def test_level1_generic_isp_node_uses_known_isp_core_group():
    graph = _semantic_graph(
        pipeline={
            "nodes": [
                {"id": "csis", "ip_ref": "ip-csis-s5e9965", "role": "csis"},
                {"id": "isp", "ip_ref": "ip-isp-s5e9965", "role": "isp"},
                {"id": "mcsc", "ip_ref": "ip-mcsc-s5e9965", "role": "mcsc"},
            ],
            "edges": [
                {"from": "csis", "to": "isp", "type": "OTF"},
                {"from": "isp", "to": "mcsc", "type": "OTF"},
            ],
        },
        ip_catalog={
            "ip-csis-s5e9965": _ip("camera", properties={"hierarchy_group": "ISP", "ip_group": "CSIS"}),
            "ip-isp-s5e9965": _ip("camera", properties={"hierarchy_group": "ISP", "ip_group": "ISP"}),
            "ip-mcsc-s5e9965": _ip("camera", properties={"hierarchy_group": "ISP", "ip_group": "MCSC"}),
        },
    )

    view = service._project_semantic_level1(graph)
    node_by_id = {node.data.id: node for node in view.nodes}

    assert node_by_id["ip-csis"].data.ip_group == "CSIS"
    assert node_by_id["grp-isp-csis"].data.view_hints.order == 9
    assert node_by_id["ip-isp"].data.ip_group == "ISP Core"
    assert node_by_id["ip-isp"].data.parent == "grp-isp-isp-core"


def test_level1_compute_hierarchy_has_explicit_order_for_gpu_npu():
    graph = _semantic_graph(
        pipeline={
            "nodes": [
                {"id": "cpu", "ip_ref": "ip-cpu-s5e9965", "role": "cpu"},
                {"id": "gpu", "ip_ref": "ip-gpu-s5e9965", "role": "gpu_renderer"},
                {"id": "npu", "ip_ref": "ip-npu-s5e9965", "role": "npu"},
                {"id": "dpu", "ip_ref": "ip-dpu-s5e9965", "role": "display_controller"},
            ],
            "edges": [
                {"from": "cpu", "to": "gpu", "type": "control"},
                {"from": "gpu", "to": "npu", "type": "M2M", "buffer": "GPU_NPU_BUF"},
                {"from": "npu", "to": "dpu", "type": "M2M", "buffer": "NPU_DPU_BUF"},
            ],
        },
        ip_catalog={
            "ip-cpu-s5e9965": _ip("cpu"),
            "ip-gpu-s5e9965": _ip("compute", properties={"hierarchy_group": "Compute", "ip_group": "SGPU"}),
            "ip-npu-s5e9965": _ip("compute", properties={"hierarchy_group": "Compute", "ip_group": "NPU"}),
            "ip-dpu-s5e9965": _ip("display", properties={"hierarchy_group": "DPU", "ip_group": "DPU"}),
        },
    )

    view = service._project_semantic_level1(graph)
    node_by_id = {node.data.id: node for node in view.nodes}

    assert node_by_id["grp-compute"].data.view_hints.order == 2
    assert node_by_id["ip-gpu"].data.hierarchy_group == "Compute"
    assert node_by_id["ip-gpu"].data.ip_group == "SGPU"
    assert node_by_id["ip-gpu"].data.parent == "grp-compute-sgpu"
    assert node_by_id["ip-npu"].data.parent == "grp-compute-npu"


def test_level1_exynos_non_camera_fixtures_use_known_semantic_groups():
    issues: list[str] = []
    known_hierarchies = set(service._LEVEL1_HIERARCHY_ORDER)
    known_ip_groups = set(service._LEVEL1_IP_GROUP_ORDER)

    for scenario_path in sorted((FIXTURE_ROOT / "02_definition").glob("uc-*.yaml")):
        raw = _load_yaml(scenario_path)
        if "camera" in str(raw.get("id") or ""):
            continue
        for variant in raw.get("variants") or []:
            view = service._project_semantic_level1(_exynos_fixture_graph_for(raw, variant))
            if view is None:
                issues.append(f"{raw['id']}/{variant['id']}: no semantic view")
                continue
            node_ids = {node.data.id for node in view.nodes}
            for node in view.nodes:
                data = node.data
                if data.parent and data.parent not in node_ids:
                    issues.append(f"{raw['id']}/{variant['id']}/{data.id}: missing parent {data.parent}")
                if data.layer == "meta" and data.type == "submodule":
                    continue
                if data.hierarchy_group not in known_hierarchies:
                    issues.append(f"{raw['id']}/{variant['id']}/{data.id}: unknown hierarchy {data.hierarchy_group}")
                if data.ip_group not in known_ip_groups:
                    issues.append(f"{raw['id']}/{variant['id']}/{data.id}: unknown IP group {data.ip_group}")
            for edge in view.edges:
                if edge.data.source not in node_ids or edge.data.target not in node_ids:
                    issues.append(f"{raw['id']}/{variant['id']}/{edge.data.id}: dangling edge")

    assert issues == []
