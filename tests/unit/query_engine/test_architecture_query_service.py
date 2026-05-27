from __future__ import annotations

import pytest

from types import SimpleNamespace

from scenario_db.api.schemas.query import (
    QueryAggregationMetric,
    QueryAggregationSpec,
    QueryPredicate,
    QueryPredicateGroup,
    QueryRequest,
    QueryResultItem,
)
from scenario_db.query_engine.service import QueryValidationError, _build_aggregations, build_facets, query_variants


class _Query:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)


class _Session:
    def __init__(self) -> None:
        self.projects = [
            SimpleNamespace(
                id="proj-demo",
                metadata_={
                    "name": "Demo Board",
                    "soc_ref": "soc-demo",
                    "board_type": "EVT0",
                },
                globals_={},
            )
        ]
        self.scenarios = [
            SimpleNamespace(
                id="uc-camera",
                project_ref="proj-demo",
                metadata_={"name": "Camera Recording", "category": ["camera"], "domain": ["imaging"]},
                pipeline={
                    "nodes": [
                        {"id": "sensor", "ip_ref": "ip-sensor-demo"},
                        {"id": "isp", "ip_ref": "ip-isp-demo"},
                        {"id": "mfc", "ip_ref": "ip-mfc-demo"},
                        {"id": "dpu", "ip_ref": "ip-dpu-demo"},
                    ],
                    "edges": [
                        {"from": "sensor", "to": "isp", "type": "OTF"},
                        {"from": "isp", "to": "mfc", "type": "M2M", "buffer": "RECORD_BUF"},
                        {"from": "isp", "to": "dpu", "type": "M2M", "buffer": "PREVIEW_BUF"},
                    ],
                    "buffers": {
                        "RECORD_BUF": {"format": "YUV420", "compression": "COMP_SBWC_LOSSLESS"},
                        "PREVIEW_BUF": {"format": "YUV420", "compression": "COMP_OFF"},
                    },
                },
                size_profile={},
            )
        ]
        self.variants = [
            SimpleNamespace(
                scenario_id="uc-camera",
                id="UHD60",
                severity="high",
                design_conditions={"resolution": "UHD", "fps": 60, "codec": "H.265"},
                design_conditions_override=None,
                size_overrides={},
                routing_switch={"disabled_nodes": ["dpu"]},
                topology_patch={},
                node_configs={},
                buffer_overrides={"RECORD_BUF": {"compression": "COMP_SBWC_LOSSLESS"}},
                ip_requirements={},
                sw_requirements={},
                violation_policy={},
                tags=["recording"],
                derived_from_variant=None,
            ),
            SimpleNamespace(
                scenario_id="uc-camera",
                id="FHD30",
                severity="nominal",
                design_conditions={"resolution": "FHD", "fps": 30, "codec": "H.264"},
                design_conditions_override=None,
                size_overrides={},
                routing_switch={},
                topology_patch={},
                node_configs={},
                buffer_overrides={},
                ip_requirements={},
                sw_requirements={},
                violation_policy={},
                tags=["preview"],
                derived_from_variant=None,
            ),
        ]
        self.ip_catalog = [
            SimpleNamespace(id="ip-sensor-demo", category="sensor"),
            SimpleNamespace(id="ip-isp-demo", category="ISP"),
            SimpleNamespace(id="ip-mfc-demo", category="MFC"),
            SimpleNamespace(id="ip-dpu-demo", category="DPU"),
        ]
        self.evidence = [
            SimpleNamespace(
                id="ev-uhd60-new",
                scenario_ref="uc-camera",
                variant_ref="UHD60",
                sw_version_hint="sw-vendor-v1.3.0",
                overall_feasibility="production_ready",
                kpi={"total_power_mw": 2100.0, "avg_ddr_bw_gbps": 10.5},
                run_info={"timestamp": "2026-05-01T00:00:00"},
            ),
            SimpleNamespace(
                id="ev-fhd30-new",
                scenario_ref="uc-camera",
                variant_ref="FHD30",
                sw_version_hint="sw-vendor-v1.3.0",
                overall_feasibility="production_ready",
                kpi={"total_power_mw": 900.0, "avg_ddr_bw_gbps": 3.2},
                run_info={"timestamp": "2026-05-01T00:00:00"},
            ),
        ]
        self.issues = []

    def query(self, model):
        table = getattr(model, "__tablename__", "")
        if table == "projects":
            return _Query(self.projects)
        if table == "scenarios":
            return _Query(self.scenarios)
        if table == "scenario_variants":
            return _Query(self.variants)
        if table == "ip_catalog":
            return _Query(self.ip_catalog)
        if table == "evidence":
            return _Query(self.evidence)
        if table == "issues":
            return _Query(self.issues)
        return _Query([])


class _FailingSession:
    def query(self, model):
        raise RuntimeError("database read failed")


def test_query_propagates_database_read_errors() -> None:
    with pytest.raises(RuntimeError, match="database read failed"):
        query_variants(_FailingSession(), QueryRequest())


def test_query_propagates_variant_resolution_errors() -> None:
    session = _Session()
    session.variants.append(
        SimpleNamespace(
            scenario_id="uc-camera",
            id="BROKEN-DERIVED",
            severity="nominal",
            design_conditions={},
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
            derived_from_variant="MISSING-PARENT",
        )
    )

    with pytest.raises(LookupError, match="Parent variant not found"):
        query_variants(session, QueryRequest())


def test_query_filters_by_axis_effective_topology_and_latest_kpi() -> None:
    request = QueryRequest(
        where=[
            QueryPredicate(field="axis.resolution", op="eq", value="UHD"),
            QueryPredicate(field="topology.uses_ip_category", op="eq", value="MFC"),
            QueryPredicate(field="topology.disabled_node", op="eq", value="dpu"),
            QueryPredicate(field="evidence.latest.kpi.total_power_mw", op="lte", value=2500),
        ],
        include=["topology_facts", "latest_evidence"],
        sort=[{"field": "evidence.latest.kpi.total_power_mw", "dir": "asc"}],
    )

    response = query_variants(_Session(), request)

    assert response.total == 1
    item = response.items[0]
    assert item.scenario_id == "uc-camera"
    assert item.variant_id == "UHD60"
    assert item.key_axes == {"resolution": "UHD", "fps": 60, "codec": "H.265"}
    assert "ip-mfc-demo" in item.active_ip_refs
    assert "ip-dpu-demo" not in item.active_ip_refs
    assert item.disabled_nodes == ["dpu"]
    assert item.buffer_refs == ["RECORD_BUF"]
    assert item.latest_evidence_id == "ev-uhd60-new"
    assert item.latest_kpi["total_power_mw"] == 2100.0


def test_query_rejects_unknown_field() -> None:
    request = QueryRequest(where=[QueryPredicate(field="raw.sql", op="eq", value="select 1")])

    with pytest.raises(QueryValidationError) as exc_info:
        query_variants(_Session(), request)

    assert "Unsupported query field" in exc_info.value.errors[0]


def test_query_combines_scope_and_sbwc_buffer_predicates() -> None:
    request = QueryRequest(
        scope={"soc_ref": "soc-demo", "project_ref": "proj-demo"},
        where=[
            QueryPredicate(field="buffer.compression", op="contains", value="SBWC"),
            QueryPredicate(field="topology.uses_buffer", op="exists", value=True),
        ],
        sort=[{"field": "variant.id", "dir": "asc"}],
    )

    response = query_variants(_Session(), request)

    assert response.errors == []
    assert response.total == 2
    assert [item.variant_id for item in response.items] == ["FHD30", "UHD60"]
    assert all(item.soc_ref == "soc-demo" for item in response.items)
    assert all(item.project_id == "proj-demo" for item in response.items)


def test_query_scope_mismatch_returns_no_rows() -> None:
    request = QueryRequest(
        scope={"soc_ref": "soc-other", "project_ref": "proj-demo"},
        where=[QueryPredicate(field="buffer.compression", op="contains", value="SBWC")],
    )

    response = query_variants(_Session(), request)

    assert response.total == 0
    assert response.items == []
    assert response.errors == []


def test_query_supports_exists_false_for_disabled_nodes() -> None:
    request = QueryRequest(where=[QueryPredicate(field="topology.disabled_node", op="exists", value=False)])

    response = query_variants(_Session(), request)

    assert response.total == 1
    assert response.items[0].variant_id == "FHD30"


def test_query_supports_or_groups_combined_with_top_level_and_predicates() -> None:
    request = QueryRequest(
        where=[QueryPredicate(field="scenario.category", op="eq", value="camera")],
        groups=[
            QueryPredicateGroup(
                join="or",
                where=[
                    QueryPredicate(field="axis.resolution", op="eq", value="UHD"),
                    QueryPredicate(field="axis.fps", op="eq", value=30),
                ],
            )
        ],
        sort=[{"field": "variant.id", "dir": "asc"}],
    )

    response = query_variants(_Session(), request)

    assert response.errors == []
    assert response.total == 2
    assert [item.variant_id for item in response.items] == ["FHD30", "UHD60"]


def test_query_supports_and_groups_for_nested_refinement() -> None:
    request = QueryRequest(
        groups=[
            QueryPredicateGroup(
                join="and",
                where=[
                    QueryPredicate(field="axis.resolution", op="eq", value="UHD"),
                    QueryPredicate(field="topology.disabled_node", op="eq", value="dpu"),
                ],
            )
        ],
    )

    response = query_variants(_Session(), request)

    assert response.errors == []
    assert response.total == 1
    assert response.items[0].variant_id == "UHD60"


def test_query_sorts_and_paginates_by_latest_kpi() -> None:
    request = QueryRequest(
        sort=[{"field": "evidence.latest.kpi.total_power_mw", "dir": "desc"}],
        limit=1,
    )

    response = query_variants(_Session(), request)

    assert response.total == 2
    assert response.has_next is True
    assert len(response.items) == 1
    assert response.items[0].variant_id == "UHD60"
    assert response.items[0].latest_kpi["total_power_mw"] == 2100.0


def test_latest_evidence_uses_utc_order_not_lexical_timestamp_order() -> None:
    session = _Session()
    session.evidence = [
        SimpleNamespace(
            id="ev-lexical-later-but-utc-older",
            scenario_ref="uc-camera",
            variant_ref="UHD60",
            sw_version_hint="sw-old",
            overall_feasibility="production_ready",
            kpi={"total_power_mw": 1800.0},
            run_info={"timestamp": "2026-05-01T09:00:00+09:00"},
        ),
        SimpleNamespace(
            id="ev-utc-newer",
            scenario_ref="uc-camera",
            variant_ref="UHD60",
            sw_version_hint="sw-new",
            overall_feasibility="production_ready",
            kpi={"total_power_mw": 1900.0},
            run_info={"timestamp": "2026-05-01T01:30:00Z"},
        ),
    ]
    request = QueryRequest(scope={"scenario_id": "uc-camera", "variant_id": "UHD60"})

    response = query_variants(session, request)

    assert response.total == 1
    assert response.items[0].latest_evidence_id == "ev-utc-newer"
    assert response.items[0].latest_sw_version == "sw-new"


def test_query_aggregates_filtered_results_by_group_and_latest_kpi_metrics() -> None:
    request = QueryRequest(
        where=[QueryPredicate(field="scenario.category", op="eq", value="camera")],
        aggregate=QueryAggregationSpec(
            group_by=["scenario.category"],
            metrics=[
                QueryAggregationMetric(
                    field="evidence.latest.kpi.total_power_mw",
                    ops=["count", "min", "avg", "p50", "p95", "max"],
                )
            ],
        ),
    )

    response = query_variants(_Session(), request)

    assert response.errors == []
    assert response.total == 2
    assert len(response.aggregations) == 1
    bucket = response.aggregations[0]
    assert bucket.key == {"scenario.category": "camera"}
    assert bucket.count == 2
    metrics = bucket.metrics["evidence.latest.kpi.total_power_mw"]
    assert metrics == {
        "count": 2,
        "min": 900.0,
        "avg": 1500.0,
        "p50": 1500.0,
        "p95": 2040.0,
        "max": 2100.0,
    }


def test_query_aggregation_explodes_collection_group_fields() -> None:
    request = QueryRequest(
        aggregate=QueryAggregationSpec(
            group_by=["topology.uses_ip_category"],
            metrics=[QueryAggregationMetric(field="evidence.latest.kpi.total_power_mw", ops=["count"])],
        )
    )

    response = query_variants(_Session(), request)

    counts = {
        bucket.key["topology.uses_ip_category"]: bucket.count
        for bucket in response.aggregations
    }
    assert counts == {"ISP": 2, "MFC": 2, "sensor": 2, "DPU": 1}


def test_query_aggregation_distinguishes_missing_group_value_from_literal_none_string() -> None:
    missing = QueryResultItem(
        project_id="proj",
        scenario_id="uc-missing",
        scenario_name="Missing",
        variant_id="v1",
        category=[],
    )
    literal = QueryResultItem(
        project_id="proj",
        scenario_id="uc-literal",
        scenario_name="Literal",
        variant_id="v1",
        category=["(none)"],
    )

    buckets = _build_aggregations(
        [missing, literal],
        QueryAggregationSpec(group_by=["scenario.category"], metrics=[]),
    )

    counts = {bucket.key["scenario.category"]: bucket.count for bucket in buckets}
    assert counts == {None: 1, "(none)": 1}


def test_query_facets_include_dynamic_axis_kpi_and_value_hints() -> None:
    response = build_facets(_Session())
    fields = {item.field: item for item in response.fields}

    assert "axis.resolution" in fields
    assert "axis.fps" in fields
    assert "evidence.latest.kpi.total_power_mw" in fields
    assert fields["topology.uses_ip_category"].values == ["DPU", "ISP", "MFC", "sensor"]
    assert fields["buffer.compression"].values == ["COMP_OFF", "COMP_SBWC_LOSSLESS"]
