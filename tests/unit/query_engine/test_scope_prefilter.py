from __future__ import annotations

from types import SimpleNamespace

import pytest

from scenario_db.api.schemas.query import QueryPredicate, QueryRequest
from scenario_db.query_engine import service as qe_service
from scenario_db.query_engine.service import (
    QueryValidationError,
    build_facets,
    invalidate_facets_cache,
    query_variants,
)


class _Query:
    def options(self, *options):
        return self

    def __init__(self, rows):
        self._rows = rows
        self.filters: list[object] = []
        self.all_calls = 0
        self.count_calls = 0

    def filter(self, *criteria):
        self.filters.extend(criteria)
        return self

    def all(self):
        self.all_calls += 1
        return list(self._rows)

    def count(self):
        self.count_calls += 1
        return len(self._rows)


def _variant(scenario_id: str, variant_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        scenario_id=scenario_id,
        id=variant_id,
        severity="nominal",
        design_conditions={"resolution": "UHD"},
        design_conditions_override=None,
        size_overrides={},
        routing_switch={},
        topology_patch={},
        node_configs={},
        buffer_overrides={},
        ip_requirements={},
        sw_requirements={},
        violation_policy={},
        tags=[],
        derived_from_variant=None,
    )


class _Session:
    def __init__(self):
        self.queries: dict[str, list[_Query]] = {}
        self.projects = [
            SimpleNamespace(id="proj-A", metadata_={"soc_ref": "soc-A", "board_type": "evt0"}, globals_={}),
        ]
        self.scenarios = [
            SimpleNamespace(
                id="uc-camera",
                project_ref="proj-A",
                metadata_={"name": "Camera", "category": ["camera"], "domain": ["imaging"]},
                pipeline={"nodes": [], "edges": [], "buffers": {}},
                size_profile={},
            ),
        ]
        self.variants = [_variant("uc-camera", "UHD60")]
        self.evidence: list[SimpleNamespace] = []
        self.issues: list[SimpleNamespace] = []
        self.ip_catalog: list[SimpleNamespace] = []

    def query(self, model):
        model = getattr(model, "class_", model)
        table = getattr(model, "__tablename__", "")
        rows = {
            "projects": self.projects,
            "scenarios": self.scenarios,
            "scenario_variants": self.variants,
            "evidence": self.evidence,
            "issues": self.issues,
            "ip_catalog": self.ip_catalog,
        }.get(table, [])
        query = _Query(rows)
        self.queries.setdefault(table, []).append(query)
        return query


def test_scenario_scope_prefilters_tables_in_sql():
    """Regression (review 4.2): a scenario/project scope must narrow the
    Scenario/Variant/Evidence loads in SQL, not only in Python predicates."""
    session = _Session()

    response = query_variants(session, QueryRequest(scope={"scenario_id": "uc-camera"}))

    assert response.total == 1
    assert session.queries["scenarios"][0].filters
    assert all(query.filters for query in session.queries["scenario_variants"])
    assert all(query.filters for query in session.queries["evidence"])
    assert all(query.filters for query in session.queries["projects"])


def test_soc_board_variant_and_severity_scope_prefilter_in_sql():
    session = _Session()

    response = query_variants(
        session,
        QueryRequest(
            scope={
                "soc_ref": "soc-A",
                "board_type": "evt0",
                "variant_id": "UHD60",
                "severity": "nominal",
            }
        ),
    )

    assert response.total == 1
    assert session.queries["projects"][0].filters
    assert session.queries["scenarios"][0].filters
    assert all(query.filters for query in session.queries["scenario_variants"])
    assert all(query.filters for query in session.queries["evidence"])


def test_ip_catalog_load_is_limited_to_pipeline_ip_refs():
    session = _Session()
    session.scenarios[0].pipeline = {
        "nodes": [{"id": "sensor", "ip_ref": "ip-sensor"}, {"id": "isp", "ip_ref": "ip-isp"}],
        "edges": [],
        "buffers": {},
    }
    session.variants[0].topology_patch = {
        "add_nodes": [{"id": "task", "ip_ref": "ip-task"}],
    }
    session.ip_catalog = [
        SimpleNamespace(id="ip-sensor", category="sensor"),
        SimpleNamespace(id="ip-isp", category="ISP"),
        SimpleNamespace(id="ip-task", category="task"),
        SimpleNamespace(id="ip-unused", category="unused"),
    ]

    response = query_variants(session, QueryRequest(scope={"scenario_id": "uc-camera"}))

    assert response.total == 1
    assert session.queries["ip_catalog"][0].filters


def test_unscoped_query_still_limits_variants_to_loaded_scenarios():
    session = _Session()

    response = query_variants(session, QueryRequest())

    assert response.total == 1
    assert not session.queries["scenarios"][0].filters
    assert session.queries["scenario_variants"][0].filters
    assert session.queries["evidence"][0].filters


def test_top_level_scalar_where_predicates_are_pushed_to_sql():
    session = _Session()

    response = query_variants(
        session,
        QueryRequest(
            where=[
                QueryPredicate(field="project.id", op="eq", value="proj-A"),
                QueryPredicate(field="scenario.id", op="in", value=["uc-camera"]),
                QueryPredicate(field="variant.id", op="eq", value="UHD60"),
                QueryPredicate(field="variant.severity", op="eq", value="nominal"),
            ]
        ),
    )

    assert response.total == 1
    assert session.queries["projects"][0].filters
    assert session.queries["scenarios"][0].filters
    assert all(query.filters for query in session.queries["scenario_variants"])
    assert all(query.filters for query in session.queries["evidence"])


def test_candidate_limit_fails_before_variant_rows_are_materialized(monkeypatch):
    session = _Session()
    session.variants.append(_variant("uc-camera", "FHD30"))
    monkeypatch.setattr(
        qe_service,
        "get_settings",
        lambda: SimpleNamespace(
            query_max_candidates=1,
            query_max_evidence_rows=20,
            query_max_issue_rows=20,
        ),
    )

    with pytest.raises(QueryValidationError, match="candidate_limit_exceeded"):
        query_variants(session, QueryRequest())

    variant_query = session.queries["scenario_variants"][0]
    assert variant_query.count_calls == 1
    assert variant_query.all_calls == 0


def test_facets_cache_disabled_by_default():
    invalidate_facets_cache()
    first = build_facets(_Session())
    second = build_facets(_Session())

    assert first is not second  # TTL 0 — every call rebuilds


def test_facets_cache_serves_within_ttl_and_invalidates(monkeypatch):
    monkeypatch.setattr(
        qe_service,
        "get_settings",
        lambda: SimpleNamespace(query_facets_cache_ttl_seconds=60.0),
    )
    invalidate_facets_cache()

    first = build_facets(_Session())
    second = build_facets(_Session())
    assert second is first  # cached within TTL

    invalidate_facets_cache()
    third = build_facets(_Session())
    assert third is not first

    invalidate_facets_cache()
