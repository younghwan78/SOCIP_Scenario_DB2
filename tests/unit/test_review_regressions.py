from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from scenario_db.api.pagination import apply_sort
from scenario_db.api.schemas.view import NodeData
from scenario_db.db.models.definition import Project, Scenario
from scenario_db.matcher.context import MatcherContext
from scenario_db.matcher.runner import evaluate
from scenario_db.sim.timeline import build_timeline_events
from scenario_db.sim.timeline_adapter import timeline_tasks
from scenario_db.view.buffers import _memory_placement
from scenario_db.view.simulation_overlay import _match_node_sim_row


@pytest.mark.parametrize("model,column", [(Project, "metadata"), (Project, "globals"), (Scenario, "metadata")])
def test_public_sort_keys_compile_to_the_requested_database_column(model, column):
    with Session() as session:
        query = apply_sort(session.query(model), model, column)
        sql = str(query.statement.compile(dialect=postgresql.dialect()))
    assert f"ORDER BY {model.__tablename__}.{column} ASC" in sql


def test_ip_shorthand_and_canonical_rule_are_equivalent():
    context = MatcherContext(ip_requirements={"ISP": {"TNR": {"mode": "strong"}}})
    assert evaluate({"ip": "ISP.TNR", "field": "mode", "op": "eq", "value": "strong"}, context)
    assert evaluate({"field": "ip.ISP.TNR.mode", "op": "eq", "value": "strong"}, context)


def test_memory_requirements_do_not_invent_buffer_placement():
    graph = SimpleNamespace(
        scenario=SimpleNamespace(pipeline={"buffers": {}}),
        variant=SimpleNamespace(ip_requirements={"llc": {"required_allocations": {"mfc": "4MB"}}}),
    )
    placement = _memory_placement(graph, "AUDIO_BUF")
    assert not placement.llc_allocated
    assert placement.expected_bw_reduction_gbps is None
    assert placement.allocation_owner is None


def test_overlay_prefers_identity_and_rejects_substrings_and_shared_catalog():
    node = NodeData.model_construct(id="display", label="Display", ip_ref="ip-display")
    wrong = {"node_id": "isp", "hw_name": "isp", "ip_ref": "ip-display"}
    right = {"node_id": "display", "power_mw": 2}
    assert _match_node_sim_row(node, [wrong]) is None
    assert _match_node_sim_row(node, [wrong, right]) is right
    projected = NodeData.model_construct(id="ip-display-out", label="Output", ip_ref="ip-display")
    row = {"node_id": "display_out"}
    assert _match_node_sim_row(projected, [wrong, row]) is row
    assert _match_node_sim_row(projected, [row, {"node_id": "display-out"}]) is None


def test_otf_and_regular_task_share_resource_reservations():
    events = build_timeline_events([
        {"id": "a", "duration_ms": 10, "resource_id": "R"},
        {"id": "b", "duration_ms": 10, "resource_id": "S"},
        {"id": "c", "duration_ms": 10, "resource_id": "R"},
    ], [{"from": "a", "to": "b", "type": "OTF"}])
    a, c = (next(event for event in events if event.task_id == name) for name in ("a", "c"))
    assert a.end_ms <= c.start_ms or c.end_ms <= a.start_ms
    assert max(a.resource_wait_ms, c.resource_wait_ms) == 10


def test_otf_frames_cannot_overlap_capacity_one_hardware():
    events = build_timeline_events([
        {"id": "a", "duration_ms": 20, "resource_id": "R"},
        {"id": "b", "duration_ms": 10, "resource_id": "S"},
    ], [{"from": "a", "to": "b", "type": "OTF"}], frame_count=3, frame_period_ms=10)
    assert [event.start_ms for event in events if event.node_id == "a" or event.task_id.startswith("a#")] == [0, 20, 40]


def test_adapter_preserves_explicit_resources_and_separates_catalog_instances():
    graph = SimpleNamespace(
        scenario=SimpleNamespace(pipeline={}), ip_catalog={},
        variant=SimpleNamespace(design_conditions={}, node_configs={}),
        pipeline_nodes=[{"id": "isp-a", "ip_ref": "ip-isp-one"},
                        {"id": "isp-b", "ip_ref": "ip-isp-two", "resource_id": "shared-isp"}],
    )
    tasks = timeline_tasks(graph)
    assert [task["hw_name"] for task in tasks] == ["ISP", "ISP"]
    assert [task["resource_id"] for task in tasks] == ["isp-a", "shared-isp"]


def test_latest_evidence_selection_preserves_timezone_and_tie_policy():
    from scenario_db.query_engine.service import _evidence_sort_key, _latest_evidence_by_variant

    rows = [SimpleNamespace(id=identity, scenario_ref="s", variant_ref="v", run_info={"timestamp": timestamp})
            for identity, timestamp in [("invalid", "not-a-date"), ("z", "2026-09-05T00:00:00Z"),
                                        ("a", "2026-09-05T09:00:00+09:00"), ("new", "2026-09-06T00:00:00Z")]]
    assert _latest_evidence_by_variant(rows)[("s", "v")] is sorted(rows, key=_evidence_sort_key, reverse=True)[0]
    assert _latest_evidence_by_variant(rows[:3])[("s", "v")].id == "z"
