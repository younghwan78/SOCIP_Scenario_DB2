from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import yaml

from dashboard.components.level2_expand_options import (
    CUSTOM_EXPAND_OPTION,
    build_level2_expand_options,
    custom_level2_expand_default,
    default_level2_expand_value,
    has_concrete_level2_options,
    level2_expand_request_target,
    selected_level2_expand_value,
)
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.view import service
from scenario_db.api.schemas.view import NodeData, NodeElement, ViewResponse, ViewSummary


FIXTURE_ROOT = Path("db_fixtures_Exynos2600_S26Plus")


def _summary() -> ViewSummary:
    return ViewSummary(
        scenario_id="uc-game-play",
        variant_id="game-fhd-60fps-npu-ai",
        name="Game Play",
        subtitle="FHD 60fps",
        period_ms=16.67,
        budget_ms=15.0,
        resolution="1920 x 1080",
        fps=60,
        variant_label="soc-exynos2600",
    )


def _node(node_id: str, label: str, *, hierarchy: str, ip_group: str, layer: str = "hw") -> NodeElement:
    return NodeElement(
        data=NodeData(
            id=node_id,
            label=label,
            type="ip",
            layer=layer,
            hierarchy_group=hierarchy,
            ip_group=ip_group,
        ),
        position={"x": 0, "y": 0},
    )


def _view(nodes: list[NodeElement]) -> ViewResponse:
    return ViewResponse(
        level=1,
        mode="level1-ip-detail",
        scenario_id="uc-game-play",
        variant_id="game-fhd-60fps-npu-ai",
        summary=_summary(),
        nodes=nodes,
        edges=[],
        risks=[],
        metadata={"layout": "level1-semantic-ip-dag"},
    )


def test_level2_expand_options_do_not_default_to_camera_when_no_camera_nodes():
    options = build_level2_expand_options(
        _view(
            [
                _node("ip-gpu", "GPU", hierarchy="Compute", ip_group="SGPU"),
                _node("ip-dpu", "DPU", hierarchy="DPU", ip_group="DPU"),
            ]
        )
    )

    labels = [option.label for option in options]
    values = [option.value for option in options]

    assert "Camera pipeline (active ISP blocks)" not in labels
    assert values[0] == "display"
    assert "gpu" in values
    assert default_level2_expand_value(options) == "display"


def test_level2_expand_options_include_only_aliases_present_in_active_graph():
    options = build_level2_expand_options(
        _view(
            [
                _node("ip-csispdp", "CSISPDP", hierarchy="ISP", ip_group="CSIS/PDP"),
                _node("ip-mfc-enc", "MFC ENC", hierarchy="CODEC", ip_group="MFC"),
                _node("ip-dpu", "DPU", hierarchy="DPU", ip_group="DPU"),
            ]
        )
    )

    assert [option.value for option in options[:3]] == ["camera", "video", "display"]
    assert default_level2_expand_value(options) == "camera"


def test_exynos2600_display_fixture_offers_display_target_even_when_dpu_is_external_layer():
    graph = _exynos2600_graph("uc-gallery-display.yaml", "disp-gallery-fhd-hdr10plus-60hz")
    level1 = service._project_semantic_level1(graph)

    options = build_level2_expand_options(level1)

    values = [option.value for option in options]
    labels = [option.label for option in options]
    assert values[0] == "display"
    assert "dpu" in values
    assert "Display output (active DPU blocks)" in labels


def test_level2_expand_options_restore_pipeline_ids_for_hyphenated_view_nodes():
    options = build_level2_expand_options(
        _view(
            [
                _node("ip-gdc-m", "GDC M", hierarchy="ISP", ip_group="GDC"),
                _node("ip-mfc-enc", "MFC ENC", hierarchy="CODEC", ip_group="MFC"),
            ]
        )
    )

    values = [option.value for option in options]

    assert "gdc_m" in values
    assert "mfc_enc" in values
    assert "gdc-m" not in values
    assert "mfc-enc" not in values


def test_level2_expand_selection_resets_stale_custom_value_when_scenario_changes():
    options = build_level2_expand_options(
        _view(
            [
                _node("ip-gpu", "GPU", hierarchy="Compute", ip_group="SGPU"),
                _node("ip-npu", "NPU", hierarchy="NPU", ip_group="NPU"),
            ]
        )
    )

    selected = selected_level2_expand_value(
        options,
        previous_value=CUSTOM_EXPAND_OPTION.value,
        previous_context="uc-camera-recording/cam-rec",
        current_context="uc-game-play/game-fhd-60fps-npu-ai",
    )

    assert selected == "gpu"


def test_level2_custom_input_starts_blank_when_no_concrete_option_and_context_changes():
    options = build_level2_expand_options(_view([]))

    assert has_concrete_level2_options(options) is False
    assert default_level2_expand_value(options) == CUSTOM_EXPAND_OPTION.value
    assert custom_level2_expand_default(
        previous_value="csispdp",
        previous_context="uc-camera-recording/cam-rec",
        current_context="uc-audio-mp3-playback/audio-aac-bt-screen-on",
    ) == ""


def test_level2_request_is_skipped_when_only_custom_option_is_blank():
    assert level2_expand_request_target(CUSTOM_EXPAND_OPTION.value, "") is None
    assert level2_expand_request_target(CUSTOM_EXPAND_OPTION.value, "   ") is None


def test_level2_request_uses_selected_node_instead_of_stale_custom_text():
    assert level2_expand_request_target("gpu", "csispdp") == "gpu"


def test_exynos2600_audio_fixture_does_not_reuse_stale_camera_custom_expand():
    graph = _exynos2600_graph("uc-audio-mp3-playback.yaml", "audio-aac-bt-screen-on")
    level1 = service._project_semantic_level1(graph)
    options = build_level2_expand_options(level1)
    current_context = "uc-audio-mp3-playback/audio-aac-bt-screen-on"

    assert has_concrete_level2_options(options) is False
    assert selected_level2_expand_value(
        options,
        previous_value=CUSTOM_EXPAND_OPTION.value,
        previous_context="uc-camera-recording/cam-rec-3rdparty-binning",
        current_context=current_context,
    ) == CUSTOM_EXPAND_OPTION.value
    custom_value = custom_level2_expand_default(
        previous_value="csispdp",
        previous_context="uc-camera-recording/cam-rec-3rdparty-binning",
        current_context=current_context,
    )
    assert custom_value == ""
    assert level2_expand_request_target(CUSTOM_EXPAND_OPTION.value, custom_value) is None


def _exynos2600_graph(scenario_file: str, variant_id: str) -> CanonicalScenarioGraph:
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
        ip_catalog=_exynos2600_catalog(),
    )


def _exynos2600_catalog() -> dict[str, SimpleNamespace]:
    catalog: dict[str, SimpleNamespace] = {}
    for path in (FIXTURE_ROOT / "00_hw").glob("ip-*.yaml"):
        raw = _load_yaml(path)
        catalog[str(raw["id"])] = SimpleNamespace(
            category=raw.get("category"),
            capabilities=raw.get("capabilities") or {},
            hierarchy=raw.get("hierarchy") or {},
        )
    return catalog


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


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


def _deep_merge(base: dict, override: dict) -> dict:
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged
