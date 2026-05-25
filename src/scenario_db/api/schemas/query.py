from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


QueryOperator = Literal[
    "eq",
    "neq",
    "in",
    "not_in",
    "gt",
    "gte",
    "lt",
    "lte",
    "contains",
    "exists",
]


class QueryPredicate(BaseModel):
    field: str
    op: QueryOperator = "eq"
    value: Any | None = None


QueryGroupJoin = Literal["and", "or"]
QueryAggregationOp = Literal["count", "min", "avg", "p50", "p95", "max"]


class QueryPredicateGroup(BaseModel):
    join: QueryGroupJoin = "or"
    where: list[QueryPredicate] = Field(default_factory=list)


class QueryAggregationMetric(BaseModel):
    field: str
    ops: list[QueryAggregationOp] = Field(default_factory=lambda: ["count"])


class QueryAggregationSpec(BaseModel):
    group_by: list[str] = Field(default_factory=list)
    metrics: list[QueryAggregationMetric] = Field(default_factory=list)
    top_n: int = Field(default=50, ge=1, le=500)


class QueryRequest(BaseModel):
    scope: dict[str, Any] = Field(default_factory=dict)
    where: list[QueryPredicate] = Field(default_factory=list)
    groups: list[QueryPredicateGroup] = Field(default_factory=list)
    aggregate: QueryAggregationSpec | None = None
    include: list[str] = Field(default_factory=list)
    sort: list[dict[str, Any]] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class QueryField(BaseModel):
    field: str
    label: str
    type: str = "string"
    operators: list[str] = Field(default_factory=list)
    values: list[Any] | None = None


class QueryFacetsResponse(BaseModel):
    fields: list[QueryField] = Field(default_factory=list)
    operators: list[str] = Field(default_factory=list)


class QueryResultItem(BaseModel):
    project_id: str
    soc_ref: str | None = None
    board_type: str | None = None
    scenario_id: str
    scenario_name: str
    variant_id: str
    severity: str | None = None
    category: list[str] = Field(default_factory=list)
    domain: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    derived: bool = False
    design_conditions: dict[str, Any] = Field(default_factory=dict)
    key_axes: dict[str, Any] = Field(default_factory=dict)
    active_ip_refs: list[str] = Field(default_factory=list)
    active_ip_categories: list[str] = Field(default_factory=list)
    edge_types: list[str] = Field(default_factory=list)
    buffer_refs: list[str] = Field(default_factory=list)
    buffer_formats: list[str] = Field(default_factory=list)
    buffer_compressions: list[str] = Field(default_factory=list)
    disabled_nodes: list[str] = Field(default_factory=list)
    latest_evidence_id: str | None = None
    latest_sw_version: str | None = None
    latest_feasibility: str | None = None
    latest_kpi: dict[str, Any] = Field(default_factory=dict)
    matched_issue_ids: list[str] = Field(default_factory=list)
    matched_issue_count: int = 0
    viewer_query: dict[str, str] = Field(default_factory=dict)


class QueryAggregationBucket(BaseModel):
    key: dict[str, Any] = Field(default_factory=dict)
    count: int
    metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)


class QueryResponse(BaseModel):
    items: list[QueryResultItem] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
    has_next: bool
    aggregations: list[QueryAggregationBucket] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
