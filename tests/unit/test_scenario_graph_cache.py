from __future__ import annotations

from types import SimpleNamespace

from scenario_db.db.repositories import scenario_graph as sg
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph


def _graph() -> CanonicalScenarioGraph:
    scenario = SimpleNamespace(
        id="uc-test",
        pipeline={
            "nodes": [
                {"id": "csis0", "ip_ref": "ip-csis-v8"},
                {"id": "isp0", "ip_ref": "ip-isp-v12"},
            ],
            "edges": [{"from": "csis0", "to": "isp0", "type": "OTF"}],
            "buffers": {},
        },
    )
    variant = SimpleNamespace(
        id="V1",
        routing_switch={},
        topology_patch={},
        size_overrides={},
    )
    return CanonicalScenarioGraph(scenario=scenario, variant=variant)


def test_effective_pipeline_computed_once_per_graph(monkeypatch):
    """Regression: pipeline_nodes/pipeline_edges must not re-run the deepcopy
    overlay resolution on every property access (O(E x N x deepcopy) in views)."""
    calls = {"count": 0}
    original = sg._effective_pipeline

    def _counting(pipeline, variant):
        calls["count"] += 1
        return original(pipeline, variant)

    monkeypatch.setattr(sg, "_effective_pipeline", _counting)

    graph = _graph()
    for _ in range(5):
        assert len(graph.pipeline_nodes) == 2
        assert len(graph.pipeline_edges) == 1
        assert graph.ip_ref_for_node("isp0") == "ip-isp-v12"

    assert calls["count"] == 1


def test_pipeline_properties_return_same_objects():
    graph = _graph()

    assert graph.pipeline_nodes is graph.pipeline_nodes
    assert graph.pipeline_edges is graph.pipeline_edges


def test_node_by_id_lookup():
    graph = _graph()

    assert graph.node_by_id("csis0") == {"id": "csis0", "ip_ref": "ip-csis-v8"}
    assert graph.node_by_id("ghost") is None
    assert graph.node_by_id(None) is None


def test_cached_pipeline_still_applies_variant_overlay():
    graph = _graph()
    graph.variant.topology_patch = {
        "add_nodes": [{"id": "mfc", "ip_ref": "ip-mfc-v14"}],
        "add_edges": [{"from": "isp0", "to": "mfc", "type": "M2M", "buffer": "BUF"}],
    }

    node_ids = [node.get("id") for node in graph.pipeline_nodes]

    assert node_ids == ["csis0", "isp0", "mfc"]
    assert graph.node_by_id("mfc") is not None
