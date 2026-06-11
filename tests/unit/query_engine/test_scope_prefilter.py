from __future__ import annotations

from types import SimpleNamespace

from scenario_db.api.schemas.query import QueryRequest
from scenario_db.query_engine import service as qe_service
from scenario_db.query_engine.service import (
    build_facets,
    invalidate_facets_cache,
    query_variants,
)


class _Query:
    def __init__(self, rows):
        self._rows = rows
        self.filters: list[object] = []

    def filter(self, *criteria):
        self.filters.extend(criteria)
        return self

    def all(self):
        return list(self._rows)


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
            SimpleNamespace(id="proj-A", metadata_={"soc_ref": "soc-A"}, globals_={}),
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


def test_unscoped_query_loads_tables_without_sql_filters():
    session = _Session()

    response = query_variants(session, QueryRequest())

    assert response.total == 1
    assert not session.queries["scenarios"][0].filters
    assert not session.queries["scenario_variants"][0].filters


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
