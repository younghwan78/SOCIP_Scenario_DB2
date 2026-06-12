from __future__ import annotations

from scenario_db.view.pipeline import _task_edge_removed


def test_task_edge_removed_uses_canonical_buffer_qualifier_semantics():
    edge = {"from": "a", "to": "b", "type": "M2M"}

    assert _task_edge_removed(edge, [{"from": "a", "to": "b", "type": "M2M", "buffer": "BUF_A"}]) is False


def test_task_edge_removed_allows_unqualified_endpoint_match():
    edge = {"from": "a", "to": "b", "type": "M2M"}

    assert _task_edge_removed(edge, [{"from": "a", "to": "b"}]) is True
