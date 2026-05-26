from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import yaml

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.view import service


FIXTURE_ROOT = Path("db_fixtures_Exynos2600_S26Plus")
GOLDEN_ROOT = Path("tests/unit/view/golden")


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


def _payload(view) -> dict:
    return view.model_dump(mode="json", exclude_none=True)


def _assert_matches_golden(name: str, payload: dict) -> None:
    expected_path = GOLDEN_ROOT / name
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert payload == expected


def test_camera_level0_topology_projection_matches_golden():
    graph = _graph("uc-camera-recording.yaml", "cam-rec-3rdparty-binning")

    view = service._project_level0_topology_v2(graph, level=0)

    _assert_matches_golden("camera_level0_topology.json", _payload(view))


def test_camera_level1_semantic_projection_matches_golden():
    graph = _graph("uc-camera-recording.yaml", "cam-rec-3rdparty-binning")

    view = service._project_semantic_level1(graph)

    assert view is not None
    _assert_matches_golden("camera_level1_semantic.json", _payload(view))


def test_camera_level2_drilldown_projection_matches_golden():
    graph = _graph("uc-camera-recording.yaml", "cam-rec-3rdparty-binning")

    view = service._project_drilldown(graph, "csispdp")

    _assert_matches_golden("camera_level2_csispdp.json", _payload(view))
