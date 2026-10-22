"""Real PostgreSQL regressions for bounded reads and detached compute inputs."""
from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from scenario_db.api.app import create_app
from scenario_db.api.deps import get_db
from scenario_db.api.schemas.arch_exploration import ArchExplorationRunRequest
from scenario_db.api.schemas.definition import ScenarioVariantResponse
from scenario_db.api.schemas.timing_budget import TimingBudgetRequest
from scenario_db.api.services import arch_exploration as arch_service
from scenario_db.api.services.analysis_inputs import resolve_analysis_selection
from scenario_db.api.services.compute_session import REQUEST_OWNED, release_read_connection
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.models.exploration import ArchExplorationRun
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.db.repositories.variant_resolution import resolve_variant_from_rows
from scenario_db.db.session import make_session_factory
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.arch_exploration import ArchExplorationSpec, explore_variant
from scenario_db.sim.models import SimulationRunConfig


SID = "uc-projecta-fhd30-recording"
VID = "FHD30-recording"
SMALL_SPEC = {
    "axes": {"statistics": ["max"], "runtime_scales": [1.0], "dvfs_headroom_levels": 0,
             "compression": {"enabled": False}, "power_options": {"enabled": False}},
}


@contextmanager
def captured_sql(engine):
    statements = []

    def capture(_conn, cursor, sql, _params, _context, _many):
        statements.append((sql, cursor.rowcount))

    event.listen(engine, "after_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(engine, "after_cursor_execute", capture)


def test_analysis_inputs_skip_decision_history_without_changing_results(engine):
    with Session(engine) as db:
        db.add(Evidence(id=f"perf-read-{uuid4().hex}", schema_version="2.2", kind="evidence.simulation",
                        scenario_ref=SID, variant_ref=VID, yaml_sha256="test", execution_context={},
                        aggregation={}, kpi={}, timeline_events=[{"padding": "x" * 32000}]))
        db.flush()
        with captured_sql(engine) as full_sql:
            full = load_canonical_graph(db, SID, VID)
        assert full.evidence
        with captured_sql(engine) as slim_sql:
            selection = resolve_analysis_selection(db, TimingBudgetRequest(scenario_id=SID, variant_id=VID))
            slim = selection.load(db)
        context_tables = ("evidence", "issues", "waivers", "reviews", "gate_rules")
        for table in context_tables:
            assert any(f"FROM {table}" in sql for sql, _ in full_sql)
            assert not any(f"FROM {table}" in sql for sql, _ in slim_sql)
        assert not slim.graph.evidence and not slim.graph.gate_rules
        config = selection.request.config
        assert build_simulation_inputs(full, config) == build_simulation_inputs(slim.graph, config)
        spec = ArchExplorationSpec.model_validate(SMALL_SPEC)
        expected = explore_variant(full, spec, config=config, dvfs_tables=slim.tables)
        actual = explore_variant(slim.graph, spec, config=config, dvfs_tables=slim.tables)
        # Includes raw input hashes, manifests, recommendations and distributions.
        assert actual == expected
        db.rollback()


def test_variant_page_resolves_only_its_ancestors_and_preserves_response(engine):
    with Session(engine) as db:
        sid = f"perf-page-{uuid4().hex}"
        project = db.query(Project.id).first()[0]
        db.add(Scenario(id=sid, project_ref=project, schema_version="2.2", yaml_sha256="test",
                        metadata_={"name": "Paged variants"}, pipeline={}))
        db.flush()
        db.add_all([
            ScenarioVariant(scenario_id=sid, id="aa-child", derived_from_variant="zz-parent",
                            design_conditions_override={"clock_mhz": 400}, tags=["child"]),
            ScenarioVariant(scenario_id=sid, id="zz-parent", severity="high",
                            design_conditions={"fps": 60}, node_configs={"node": {"mode": "base"}}),
            *[ScenarioVariant(scenario_id=sid, id=f"sibling-{i:03}", node_configs={"padding": "x" * 1000})
              for i in range(120)],
        ])
        db.flush()
        all_rows = {row.id: row for row in db.query(ScenarioVariant).filter_by(scenario_id=sid).all()}
        expected = ScenarioVariantResponse.model_validate(
            resolve_variant_from_rows(all_rows, sid, "aa-child")).model_dump(mode="json")
        db.expunge_all()
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        with captured_sql(engine) as statements:
            response = TestClient(app).get(f"/api/v1/scenarios/{sid}/variants",
                                           params={"limit": 1, "sort_by": "id"})
        assert response.status_code == 200, response.text
        assert response.json()["items"] == [expected]
        assert response.json()["total"] == 122
        row_counts = [count for sql, count in statements
                      if "FROM scenario_variants" in sql and "count(" not in sql]
        assert row_counts == [1, 1]  # page + parent; the 120 siblings are never materialized
        db.rollback()


def test_read_release_returns_connection_and_keeps_loaded_graph_usable(engine):
    idle = engine.pool.checkedout()
    with Session(engine, info={REQUEST_OWNED: True}) as db:
        graph = load_canonical_graph(db, SID, VID, include_decision_context=False)
        config = SimulationRunConfig()
        expected = build_simulation_inputs(graph, config)
        assert engine.pool.checkedout() == idle + 1
        with captured_sql(engine) as statements:
            assert release_read_connection(db)
            assert not db.in_transaction()
            assert engine.pool.checkedout() == idle
            assert inspect(graph.scenario).detached and not inspect(graph.scenario).expired_attributes
            assert build_simulation_inputs(graph, config) == expected
        assert statements == []


@pytest.mark.parametrize("state", ["caller", "new", "dirty", "deleted", "nested"])
def test_read_release_preserves_caller_or_write_transaction(engine, state):
    with Session(engine, info={} if state == "caller" else {REQUEST_OWNED: True}) as db:
        row = db.get(Scenario, SID)
        if state == "new":
            db.add(Project(id="pending-perf-project", schema_version="2.2", yaml_sha256="pending"))
        elif state == "dirty":
            row.yaml_sha256 = "pending"
        elif state == "deleted":
            db.delete(row)
        elif state == "nested":
            db.begin_nested()
        tx, nested = db.get_transaction(), db.get_nested_transaction()
        before = (set(db.new), set(db.dirty), set(db.deleted), engine.pool.checkedout())
        assert not release_read_connection(db)
        assert db.get_transaction() is tx and db.get_nested_transaction() is nested
        assert inspect(row).persistent
        assert (set(db.new), set(db.dirty), set(db.deleted), engine.pool.checkedout()) == before
        db.rollback()


def test_read_release_does_not_open_an_idle_session(engine):
    with Session(engine, info={REQUEST_OWNED: True}) as db:
        with captured_sql(engine) as statements:
            assert not release_read_connection(db)
        assert not db.in_transaction() and statements == []


def test_http_arch_compute_releases_pool_and_persists_identical_results(engine, demo_cleanup, monkeypatch):
    request = ArchExplorationRunRequest(scenario_ids=[SID], variant_ids=[VID, "UHD60-HDR10-H265"],
                                       spec=SMALL_SPEC)
    with Session(engine) as db:
        expected = arch_service.run_exploration(db, request.model_copy(deep=True))
        expected_row = db.get(ArchExplorationRun, expected["id"])
        expected_hash, expected_spec = expected_row.input_hash, expected_row.spec
    assert engine.pool.checkedout() == 0
    original = arch_service.explore_variant
    computed = []

    def observe(graph, *args, **kwargs):
        assert engine.pool.checkedout() == 0
        assert inspect(graph.scenario).detached
        result = original(graph, *args, **kwargs)
        assert engine.pool.checkedout() == 0
        computed.append(graph.variant_id)
        return result

    monkeypatch.setattr(arch_service, "explore_variant", observe)
    app = create_app()
    # Exercise the real get_db dependency, including the ownership marker.
    app.state.session_factory = make_session_factory(engine)
    response = TestClient(app).post("/api/v1/arch/exploration/runs",
                                    json=request.model_dump(mode="json", exclude_unset=True))
    assert response.status_code == 200, response.text
    actual = response.json()
    assert sorted(computed) == sorted(request.variant_ids)
    for key in ("variants", "errors", "summary", "spec"):
        assert actual[key] == expected[key]
    assert engine.pool.checkedout() == 0
    with Session(engine) as db:
        stored = db.get(ArchExplorationRun, actual["id"])
        assert stored is not None and stored.variants == expected["variants"]
        assert stored.input_hash == expected_hash and stored.spec == expected_spec


def test_uncommitted_arch_call_keeps_its_transaction_even_if_release_requested(engine, monkeypatch):
    original = arch_service.explore_variant
    with Session(engine, info={REQUEST_OWNED: True}) as db:
        db.get(Scenario, SID)
        tx = db.get_transaction()

        def observe(graph, *args, **kwargs):
            assert db.get_transaction() is tx and engine.pool.checkedout() == 1
            assert inspect(graph.scenario).persistent
            return original(graph, *args, **kwargs)

        monkeypatch.setattr(arch_service, "explore_variant", observe)
        request = ArchExplorationRunRequest(scenario_ids=[SID], variant_ids=[VID], spec=SMALL_SPEC)
        result = arch_service.run_exploration(db, request, commit=False, release_connection=True)
        assert db.get_transaction() is tx
        db.rollback()
        assert db.get(ArchExplorationRun, result["id"]) is None
