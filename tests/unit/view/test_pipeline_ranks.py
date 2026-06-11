from __future__ import annotations

from types import SimpleNamespace

from scenario_db.view.service import _pipeline_ranks


def _graph(nodes: list[str], edges: list[tuple[str, str]]) -> SimpleNamespace:
    return SimpleNamespace(
        scenario_id="uc-test",
        variant_id="V1",
        pipeline_nodes=[{"id": node_id} for node_id in nodes],
        pipeline_edges=[{"from": src, "to": dst, "type": "OTF"} for src, dst in edges],
    )


def test_pipeline_ranks_orders_dag_topologically():
    graph = _graph(["mfc", "isp0", "csis0"], [("csis0", "isp0"), ("isp0", "mfc")])

    ranks = _pipeline_ranks(graph)

    assert ranks["csis0"] < ranks["isp0"] < ranks["mfc"]


def test_pipeline_ranks_terminates_on_cycle():
    """Regression: a pipeline cycle must not hang the relaxation loop."""
    graph = _graph(["a", "b", "c"], [("a", "b"), ("b", "c"), ("c", "a")])

    ranks = _pipeline_ranks(graph)

    assert set(ranks) == {"a", "b", "c"}


def test_pipeline_ranks_terminates_on_self_loop():
    graph = _graph(["a"], [("a", "a")])

    ranks = _pipeline_ranks(graph)

    assert set(ranks) == {"a"}
