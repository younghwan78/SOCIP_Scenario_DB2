from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from scenario_db.api.app import create_app
from scenario_db.api.deps import get_db
from scenario_db.api.schemas.query import QueryRequest
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant
from scenario_db.db.models.evidence import Evidence
from scenario_db.query_engine import service


@pytest.fixture
def catalog_db(engine):
    with Session(engine) as db:
        db.add(Project(id="perf-project", schema_version="2.2", yaml_sha256="test",
                       metadata_={"name": "Perf Board", "soc_ref": "perf-soc", "board_type": "EVT"}))
        db.flush()
        db.add_all([Scenario(id=f"perf-{i:03}", project_ref="perf-project", schema_version="2.2",
                             yaml_sha256="test", metadata_={"name": "Same name", "category": ["camera"]},
                             pipeline={"nodes": [], "edges": [], "buffers": {}, "padding": "x" * 16000})
                    for i in range(110)])
        db.flush()
        db.add_all([
            ScenarioVariant(scenario_id="perf-000", id="parent-a", severity="high", design_conditions={"fps": 60}),
            ScenarioVariant(scenario_id="perf-000", id="child-only", derived_from_variant="parent-a"),
            ScenarioVariant(scenario_id="perf-001", id="parent-b", severity="low"),
            ScenarioVariant(scenario_id="perf-001", id="child-only", derived_from_variant="parent-b"),
            # Parent names are reused in another scenario; they are not ancestors.
            ScenarioVariant(scenario_id="perf-000", id="parent-b"),
            ScenarioVariant(scenario_id="perf-001", id="parent-a"),
        ])
        db.flush()
        yield db
        db.rollback()


@pytest.fixture
def catalog_client(catalog_db):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: catalog_db
    # No lifespan: the isolated PostgreSQL fixture owns this transaction.
    yield TestClient(app)


def test_summary_pages_search_sort_scope_and_selected_id(catalog_client):
    params = {"project_ref": "perf-project", "limit": 100, "sort_by": "name"}
    first = catalog_client.get("/api/v1/catalog/scenarios", params=params)
    assert first.status_code == 200
    first = first.json()
    last = catalog_client.get("/api/v1/catalog/scenarios", params={**params, "offset": 100}).json()
    assert first["total"] == last["total"] == 110
    assert first["has_next"] and not last["has_next"]
    assert len(first["items"]) == 100 and len(last["items"]) == 10
    assert len({row["id"] for row in first["items"] + last["items"]}) == 110
    assert "pipeline" not in first["items"][0]
    assert first["items"][0]["soc_ref"] == "perf-soc"
    selected = catalog_client.get("/api/v1/catalog/scenarios", params={**params, "id": "perf-109", "limit": 1}).json()
    assert selected["items"][0]["id"] == "perf-109"
    for extra in ({"q": "CAMERA"}, {"board_type": "EVT", "soc_ref": "perf-soc"}):
        assert catalog_client.get("/api/v1/catalog/scenarios", params={**params, **extra}).json()["total"] == 110
    for extra in ({"q": "%"}, {"soc_ref": "different"}, {"board_type": "different"}):
        assert catalog_client.get("/api/v1/catalog/scenarios", params={**params, **extra}).json()["total"] == 0
    assert catalog_client.get("/api/v1/catalog/variants").status_code == 422
    variants = catalog_client.get("/api/v1/catalog/variants", params={"scenario_id": "perf-000", "id": "child-only"}).json()
    assert variants["items"][0]["scenario_id"] == "perf-000"
    assert catalog_client.get("/api/v1/catalog/variants", params={"scenario_id": "perf-000", "project_ref": "other"}).json()["total"] == 0
    assert catalog_client.get("/api/v1/scenarios/perf-000").json()["pipeline"]["padding"] == "x" * 16000


def test_summary_sql_never_loads_pipeline_or_variant_overlays(catalog_client, engine):
    statements = []
    def capture(_conn, _cursor, sql, _params, _context, _many):
        statements.append(sql)
    event.listen(engine, "before_cursor_execute", capture)
    try:
        for kind, params in [("soc-platforms", {}), ("projects", {}), ("scenarios", {"project_ref": "perf-project"}),
                             ("variants", {"scenario_id": "perf-000"})]:
            assert catalog_client.get(f"/api/v1/catalog/{kind}", params=params).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 8  # count + page, independent of rows/ancestors
    assert all(".pipeline" not in sql and ".node_configs" not in sql and ".globals" not in sql for sql in statements)


def test_variant_scope_narrows_scenarios_before_candidate_guard(catalog_db, monkeypatch):
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(query_max_candidates=10))
    response = service.query_variants(catalog_db, QueryRequest(where=[{"field": "variant.id", "value": " CHILD-ONLY "}]))
    assert {(row.scenario_id, row.variant_id) for row in response.items} == {("perf-000", "child-only"), ("perf-001", "child-only")}
    rows = service._include_variant_parent_rows(catalog_db, catalog_db.query(ScenarioVariant).filter_by(id="child-only").all())
    assert {(row.scenario_id, row.id) for row in rows} == {("perf-000", "child-only"), ("perf-001", "child-only"),
                                                          ("perf-000", "parent-a"), ("perf-001", "parent-b")}


@pytest.mark.parametrize("groups", [
    [{"join": "and", "where": [{"field": "variant.id", "value": "CHILD-ONLY"}, {"field": "variant.severity", "value": "HIGH"}]}],
    [{"join": "or", "where": [{"field": "scenario.id", "value": "perf-000"}, {"field": "scenario.id", "value": "perf-001"}]}],
    [{"join": "or", "where": [{"field": "scenario.id", "value": "perf-000"}, {"field": "variant.severity", "value": "low"}]}],
])
def test_pushdown_preserves_inheritance_group_aggregations_and_page(catalog_db, monkeypatch, groups):
    request = QueryRequest(groups=groups, aggregate={"group_by": ["variant.severity"]},
                           sort=[{"field": "scenario.id", "dir": "desc"}], limit=1, offset=1)
    actual = service.query_variants(catalog_db, request).model_dump()
    # Reference evaluates all candidates with the public predicate evaluator.
    monkeypatch.setattr(service, "_pushdown_scope", lambda predicates: {})
    expected = service.query_variants(catalog_db, request).model_dump()
    assert actual == expected


def test_latest_evidence_materializes_context_only_for_winner(catalog_db, engine):
    for i, timestamp in enumerate(["bad", None, "2026-01-01T09:00:00+09:00", "2026-01-01T01:00:00Z", "2026-01-01T01:00:00+00:00"]):
        catalog_db.add(Evidence(id=f"perf-evidence-{i}", schema_version="2.2", kind="evidence.simulation",
                                scenario_ref="perf-000", variant_ref="child-only", yaml_sha256="test",
                                execution_context={"padding": "x" * 16000}, resolution_result={}, aggregation={},
                                kpi={"power": i}, run_info={"timestamp": timestamp}))
    catalog_db.add(Evidence(id="perf-measurement", schema_version="2.2", kind="evidence.measurement",
                            scenario_ref="perf-000", variant_ref="child-only", yaml_sha256="test",
                            execution_context={}, aggregation={}, kpi={"power": 100}, run_info={"timestamp": "2099-01-01"}))
    catalog_db.flush()
    expected = service._latest_evidence_by_variant(catalog_db.query(Evidence).filter_by(kind="evidence.simulation", scenario_ref="perf-000").all())
    expected_id = expected[("perf-000", "child-only")].id
    catalog_db.expunge_all()
    statements = []
    def capture(_conn, cursor, sql, _params, _context, _many):
        statements.append((sql, cursor.rowcount))
    event.listen(engine, "after_cursor_execute", capture)
    try:
        rows = service._load_scoped_evidence(catalog_db, {"perf-000"}, {"child-only"}, max_rows=20)
    finally:
        event.remove(engine, "after_cursor_execute", capture)
    assert [row.id for row in rows] == [expected_id] == ["perf-evidence-4"]
    assert rows[0].kpi == {"power": 4}
    assert "timeline_events" in inspect(rows[0]).unloaded
    detail_reads = [(sql, count) for sql, count in statements if "evidence.execution_context" in sql and not sql.startswith("SELECT count(")]
    assert len(detail_reads) == 1 and detail_reads[0][1] == 1
    assert any("evidence.run_info" in sql and count == 5 for sql, count in statements)
    with pytest.raises(service.QueryValidationError, match="candidate_limit_exceeded"):
        service._load_scoped_evidence(catalog_db, {"perf-000"}, {"child-only"}, max_rows=4)


def test_canonical_graph_loads_only_selected_variant_and_ancestors(catalog_db, engine):
    from dataclasses import asdict
    from scenario_db.db.repositories.scenario_graph import load_canonical_graph
    from scenario_db.db.repositories.variant_resolution import resolve_variant, resolve_variant_from_rows

    catalog_db.add_all([ScenarioVariant(scenario_id="perf-000", id=f"sibling-{i}", node_configs={"padding": "x" * 1000})
                       for i in range(120)])
    catalog_db.flush()
    all_rows = {row.id: row for row in catalog_db.query(ScenarioVariant).filter_by(scenario_id="perf-000").all()}
    expected = asdict(resolve_variant_from_rows(all_rows, "perf-000", "child-only"))
    catalog_db.expunge_all()
    statements = []
    def capture(_conn, cursor, sql, _params, _context, _many):
        if "FROM scenario_variants" in sql:
            statements.append(cursor.rowcount)
    event.listen(engine, "after_cursor_execute", capture)
    try:
        graph = load_canonical_graph(catalog_db, "perf-000", "child-only", include_evidence_details=False)
    finally:
        event.remove(engine, "after_cursor_execute", capture)
    assert asdict(graph.variant) == expected
    assert statements == [1, 1]  # 120 siblings and unrelated parent are not read
    assert resolve_variant(catalog_db, "perf-000", "missing") is None
    child = catalog_db.query(ScenarioVariant).filter_by(scenario_id="perf-000", id="child-only").one()
    child.derived_from_variant = "missing"
    catalog_db.flush()
    with pytest.raises(LookupError, match="Parent variant not found"):
        resolve_variant(catalog_db, "perf-000", "child-only")
    child.derived_from_variant = "child-only"
    catalog_db.flush()
    with pytest.raises(ValueError, match="Circular variant inheritance"):
        resolve_variant(catalog_db, "perf-000", "child-only")
