from __future__ import annotations

from types import SimpleNamespace

from scenario_db.api.routers.explorer import (
    _count_matching_ips,
    _count_matching_socs,
    _count_matching_sw_profiles,
    _filtered_rows,
    _paged_scenarios,
    _paged_variants,
    variant_matrix,
)
from scenario_db.db.models.capability import IpCatalog, SocPlatform, SwProfile
from scenario_db.db.models.definition import Project, Scenario, ScenarioVariant


class _Query:
    def __init__(self, model, rows):
        self.model = model
        self.rows = rows
        self.filters = []

    def filter(self, *criteria):
        self.filters.extend(criteria)
        return self

    def order_by(self, *criteria):
        return self

    def all(self):
        if self.model in {Scenario, ScenarioVariant} and not self.filters:
            raise AssertionError(f"{self.model.__name__} must be constrained before all()")
        return self.rows


class _Session:
    def __init__(self):
        self.queries = {}
        project = Project(
            id="proj-A",
            schema_version="2.2",
            metadata_={"soc_ref": "soc-A", "board_type": "ERD"},
            yaml_sha256="sha",
        )
        scenario = Scenario(
            id="uc-camera",
            schema_version="2.2",
            project_ref="proj-A",
            metadata_={},
            pipeline={"nodes": [], "edges": []},
            yaml_sha256="sha",
        )
        variant = ScenarioVariant(
            scenario_id="uc-camera",
            id="v1",
            severity="medium",
        )
        self.rows = {
            Project: [project],
            Scenario: [scenario],
            ScenarioVariant: [variant],
        }

    def query(self, model):
        query = _Query(model, self.rows[model])
        self.queries[model] = query
        return query


def test_filtered_rows_constrains_scenarios_and_variants_before_loading():
    session = _Session()

    projects, scenarios, variants = _filtered_rows(
        session,
        soc_ref="soc-A",
        board_type="ERD",
        project_ref=None,
    )

    assert [row.id for row in projects] == ["proj-A"]
    assert [row.id for row in scenarios] == ["uc-camera"]
    assert [row.id for row in variants] == ["v1"]
    assert session.queries[Scenario].filters
    assert session.queries[ScenarioVariant].filters


class _CountQuery:
    def __init__(self, model):
        self.model = model
        self.filters = []

    def filter(self, *criteria):
        self.filters.extend(criteria)
        return self

    def all(self):
        raise AssertionError(f"{self.model.__name__} count helper must not load all rows")

    def count(self):
        return 3


class _CountSession:
    def __init__(self):
        self.queries = {}

    def query(self, model):
        query = _CountQuery(model)
        self.queries[model] = query
        return query


def test_count_helpers_use_sql_count_without_loading_all_rows():
    session = _CountSession()

    assert _count_matching_socs(session, {"soc-A"}) == 3
    assert _count_matching_ips(session, {"soc-A"}) == 3
    assert _count_matching_sw_profiles(session, {"soc-A"}) == 3
    assert session.queries[SocPlatform].filters
    assert session.queries[IpCatalog].filters
    assert session.queries[SwProfile].filters


class _PagingQuery:
    def __init__(self, model, rows):
        self.model = model
        self.rows = rows
        self.filters = []
        self.offset_value = None
        self.limit_value = None

    def filter(self, *criteria):
        self.filters.extend(criteria)
        return self

    def order_by(self, *criteria):
        return self

    def offset(self, value):
        self.offset_value = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def count(self):
        return len(self.rows)

    def all(self):
        if self.offset_value is None or self.limit_value is None:
            raise AssertionError(f"{self.model.__name__} page query must apply SQL offset/limit before all()")
        return self.rows[self.offset_value : self.offset_value + self.limit_value]


class _PagingSession:
    def __init__(self):
        self.queries = {}
        self.rows = {
            Scenario: [
                Scenario(id=f"uc-{idx}", schema_version="2.2", project_ref="proj-A", metadata_={}, pipeline={}, yaml_sha256="sha")
                for idx in range(5)
            ],
            ScenarioVariant: [
                ScenarioVariant(scenario_id="uc-1", id=f"v{idx}", severity="medium")
                for idx in range(5)
            ],
        }

    def query(self, model):
        query = _PagingQuery(model, self.rows[model])
        self.queries[model] = query
        return query


def test_paged_scenarios_applies_sql_offset_and_limit_before_loading_rows():
    session = _PagingSession()

    rows, total = _paged_scenarios(
        session,
        project_ids={"proj-A"},
        categories=None,
        domains=None,
        scenario_ids=None,
        severities=None,
        limit=2,
        offset=1,
    )

    assert total == 5
    assert [row.id for row in rows] == ["uc-1", "uc-2"]
    assert session.queries[Scenario].offset_value == 1
    assert session.queries[Scenario].limit_value == 2


def test_paged_variants_applies_sql_offset_and_limit_before_loading_rows():
    session = _PagingSession()

    rows, total = _paged_variants(
        session,
        scenario_ids={"uc-1"},
        severities=None,
        limit=2,
        offset=2,
    )

    assert total == 5
    assert [row.id for row in rows] == ["v2", "v3"]
    assert session.queries[ScenarioVariant].offset_value == 2
    assert session.queries[ScenarioVariant].limit_value == 2


class _VariantMatrixQuery:
    def __init__(self, rows):
        self.rows = rows
        self.offset_value = 0
        self.limit_value = None

    def filter(self, *criteria):
        return self

    def order_by(self, *criteria):
        return self

    def count(self):
        return len(self.rows)

    def offset(self, value):
        self.offset_value = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def all(self):
        if self.limit_value is None:
            return list(self.rows)
        return self.rows[self.offset_value : self.offset_value + self.limit_value]


class _VariantMatrixSession:
    def __init__(self):
        self.project = SimpleNamespace(
            id="proj-A",
            metadata_={"soc_ref": "soc-A", "board_type": "ERD"},
            globals_={},
        )
        self.scenario = SimpleNamespace(
            id="uc-camera",
            project_ref="proj-A",
            metadata_={"name": "Camera", "category": ["camera"], "domain": ["imaging"]},
            pipeline={"nodes": [], "edges": []},
        )
        self.variants = [
            SimpleNamespace(
                scenario_id="uc-camera",
                id="v-fps",
                severity="nominal",
                design_conditions={"fps": 30},
                routing_switch={},
                buffer_overrides={},
                node_configs={},
                tags=[],
            ),
            SimpleNamespace(
                scenario_id="uc-camera",
                id="v-codec",
                severity="nominal",
                design_conditions={"codec": "H265"},
                routing_switch={},
                buffer_overrides={},
                node_configs={},
                tags=[],
            ),
        ]

    def query(self, model):
        table = getattr(model, "__tablename__", "")
        if table == "projects":
            return _VariantMatrixQuery([self.project])
        if table == "scenarios":
            return _VariantMatrixQuery([self.scenario])
        if table == "scenario_variants":
            return _VariantMatrixQuery(self.variants)
        raise AssertionError(f"Unexpected query model: {model!r}")


def test_variant_matrix_axis_keys_are_based_on_filtered_result_not_current_page():
    response = variant_matrix(
        soc_ref=None,
        board_type=None,
        project_ref=None,
        category=None,
        domain=None,
        scenario_id=None,
        severity=None,
        limit=1,
        offset=0,
        db=_VariantMatrixSession(),
    )

    assert [item.variant_id for item in response.items] == ["v-fps"]
    assert response.total == 2
    assert response.axis_keys == ["fps", "codec"]
