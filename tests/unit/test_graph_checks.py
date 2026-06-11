from __future__ import annotations

from scenario_db.graph_checks import find_data_flow_cycle


def _nodes(*ids: str) -> list[dict]:
    return [{"id": node_id} for node_id in ids]


def test_acyclic_pipeline_returns_none():
    nodes = _nodes("csis0", "isp0", "mfc")
    edges = [
        {"from": "csis0", "to": "isp0", "type": "OTF"},
        {"from": "isp0", "to": "mfc", "type": "M2M", "buffer": "RECORD_BUF"},
    ]

    assert find_data_flow_cycle(nodes, edges) is None


def test_data_flow_cycle_returns_closed_path():
    nodes = _nodes("a", "b", "c")
    edges = [
        {"from": "a", "to": "b", "type": "OTF"},
        {"from": "b", "to": "c", "type": "M2M", "buffer": "BUF"},
        {"from": "c", "to": "a", "type": "vOTF", "buffer": "BUF"},
    ]

    cycle = find_data_flow_cycle(nodes, edges)

    assert cycle is not None
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {"a", "b", "c"}
    # Consecutive path entries must be real forward edges.
    edge_set = {("a", "b"), ("b", "c"), ("c", "a")}
    for src, dst in zip(cycle, cycle[1:]):
        assert (src, dst) in edge_set


def test_control_edges_do_not_count_as_cycle():
    nodes = _nodes("isp0", "npu0")
    edges = [
        {"from": "isp0", "to": "npu0", "type": "M2M", "buffer": "BUF"},
        {"from": "npu0", "to": "isp0", "type": "control"},
    ]

    assert find_data_flow_cycle(nodes, edges) is None


def test_self_loop_is_detected():
    cycle = find_data_flow_cycle(_nodes("a"), [{"from": "a", "to": "a", "type": "OTF"}])

    assert cycle == ["a", "a"]


def test_edges_with_unknown_endpoints_are_ignored():
    nodes = _nodes("a", "b")
    edges = [
        {"from": "a", "to": "b", "type": "OTF"},
        {"from": "b", "to": "ghost", "type": "M2M", "buffer": "BUF"},
        {"from": "ghost", "to": "a", "type": "M2M", "buffer": "BUF"},
    ]

    assert find_data_flow_cycle(nodes, edges) is None


def test_source_target_key_aliases_supported():
    nodes = _nodes("a", "b")
    edges = [
        {"source": "a", "target": "b", "type": "OTF"},
        {"from": "b", "to": "a", "type": "M2M", "buffer": "BUF"},
    ]

    cycle = find_data_flow_cycle(nodes, edges)

    assert cycle is not None
    assert cycle[0] == cycle[-1]


def test_cycle_in_disconnected_component_is_found():
    nodes = _nodes("a", "b", "x", "y")
    edges = [
        {"from": "a", "to": "b", "type": "OTF"},
        {"from": "x", "to": "y", "type": "OTF"},
        {"from": "y", "to": "x", "type": "M2M", "buffer": "BUF"},
    ]

    cycle = find_data_flow_cycle(nodes, edges)

    assert cycle is not None
    assert set(cycle) == {"x", "y"}
