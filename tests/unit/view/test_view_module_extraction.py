from __future__ import annotations

from types import SimpleNamespace

from scenario_db.api.schemas.view import NodeData, NodeElement
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph


def test_sample_data_module_owns_sample_level0_builder():
    from scenario_db.view.demo.sample_data import build_sample_level0

    view = build_sample_level0()

    assert view.level == 0
    assert view.scenario_id == "uc-camera-recording"
    assert view.nodes


def test_simulation_overlay_module_exports_overlay_entrypoint():
    from scenario_db.view.simulation_overlay import apply_simulation_overlay

    assert callable(apply_simulation_overlay)


def test_graph_utils_owns_common_edge_id_and_size_helpers():
    from scenario_db.view.graph_utils import (
        edge_source,
        edge_target,
        parse_size,
        resolution_to_size,
        safe_id,
    )

    assert edge_source({"from": "a", "source": "fallback"}) == "a"
    assert edge_source({"source": "fallback"}) == "fallback"
    assert edge_target({"to": "b", "target": "fallback"}) == "b"
    assert safe_id("GDC_DPU_BUF") == "gdc-dpu-buf"
    assert parse_size([1920, 1080]) == (1920, 1080)
    assert resolution_to_size("FHD") == "1920x1080"


def test_response_module_owns_view_response_assembly():
    from scenario_db.view.response import build_view_response

    graph = CanonicalScenarioGraph(
        scenario=SimpleNamespace(
            id="uc-camera",
            project_ref="proj-A",
            metadata_={"name": "Camera"},
            pipeline={"nodes": [], "edges": []},
            size_profile={"anchors": {"record_out": "1920x1080"}},
        ),
        variant=SimpleNamespace(
            id="v1",
            design_conditions={"resolution": "FHD", "fps": 30},
            size_overrides={},
            routing_switch={},
            topology_patch={},
            node_configs={},
            buffer_overrides={},
            ip_requirements={},
            sw_requirements={},
            resolved=True,
            inheritance_chain=["v1"],
        ),
        soc=SimpleNamespace(id="soc-A"),
    )

    view = build_view_response(
        graph=graph,
        level=1,
        mode="semantic",
        nodes=[NodeElement(data=NodeData(id="n1", label="N1", type="ip", layer="hw"), position={"x": 0, "y": 0})],
        edges=[],
        metadata={"layout": "test"},
    )

    assert view.scenario_id == "uc-camera"
    assert view.variant_id == "v1"
    assert view.summary.name == "Camera"
    assert view.metadata["variant_overlay"]["resolved"] is True


def test_level1_semantic_module_exports_projection_entrypoint():
    from scenario_db.view.level1_semantic import project_semantic_level1

    assert callable(project_semantic_level1)


def test_level2_semantic_module_exports_drilldown_entrypoint():
    from scenario_db.view.level2_semantic import project_drilldown

    assert callable(project_drilldown)


def test_reference_module_exports_legacy_reference_entrypoints():
    from scenario_db.view.reference import project_level2_reference, project_reference_level1

    assert callable(project_level2_reference)
    assert callable(project_reference_level1)


def test_view_service_requires_explicit_db_session_for_projection():
    import pytest

    from scenario_db.view import service

    with pytest.raises(ValueError, match="db session is required"):
        service.project_level0("uc-camera-recording", "cam-rec-3rdparty-binning", db=None)
