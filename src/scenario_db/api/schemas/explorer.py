from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ExplorerCount(BaseModel):
    key: str
    count: int


class ImportBatchSummary(BaseModel):
    id: str
    kind: str
    status: str
    target_id: str | None = None
    actor: str | None = None
    note: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    validation_valid: bool | None = None
    validation_issue_count: int = 0
    applied_document_counts: dict[str, int] = Field(default_factory=dict)


class ExplorerSummaryResponse(BaseModel):
    filters: dict[str, Any] = Field(default_factory=dict)
    totals: dict[str, int] = Field(default_factory=dict)
    category_counts: list[ExplorerCount] = Field(default_factory=list)
    severity_counts: list[ExplorerCount] = Field(default_factory=list)
    board_counts: list[ExplorerCount] = Field(default_factory=list)
    latest_import_batches: list[ImportBatchSummary] = Field(default_factory=list)


class ScenarioCatalogItem(BaseModel):
    soc_ref: str | None = None
    board_type: str | None = None
    board_name: str | None = None
    project_id: str
    project_name: str | None = None
    scenario_id: str
    scenario_name: str
    category: list[str] = Field(default_factory=list)
    domain: list[str] = Field(default_factory=list)
    variant_count: int
    severity_counts: dict[str, int] = Field(default_factory=dict)
    sensor_module_ref: str | None = None
    display_module_ref: str | None = None
    default_sw_profile_ref: str | None = None
    node_count: int
    edge_count: int
    buffer_count: int
    default_variant_id: str | None = None
    viewer_query: dict[str, str] = Field(default_factory=dict)


class ScenarioCatalogResponse(BaseModel):
    filters: dict[str, Any] = Field(default_factory=dict)
    items: list[ScenarioCatalogItem] = Field(default_factory=list)
    total: int


class VariantMatrixItem(BaseModel):
    soc_ref: str | None = None
    board_type: str | None = None
    project_id: str
    scenario_id: str
    scenario_name: str
    category: list[str] = Field(default_factory=list)
    variant_id: str
    severity: str | None = None
    design_conditions: dict[str, Any] = Field(default_factory=dict)
    key_fields: dict[str, Any] = Field(default_factory=dict)
    enabled_nodes: int | None = None
    disabled_nodes: list[str] = Field(default_factory=list)
    disabled_edges: int = 0
    buffer_override_count: int = 0
    node_config_count: int = 0
    tags: list[str] = Field(default_factory=list)
    viewer_query: dict[str, str] = Field(default_factory=dict)


class VariantMatrixResponse(BaseModel):
    filters: dict[str, Any] = Field(default_factory=dict)
    axis_keys: list[str] = Field(default_factory=list)
    items: list[VariantMatrixItem] = Field(default_factory=list)
    total: int


class ImportHealthIssue(BaseModel):
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    document_kind: str | None = None
    document_id: str | None = None
    path: str | None = None
    fix_hint: str | None = None


class ImportHealthResponse(BaseModel):
    filters: dict[str, Any] = Field(default_factory=dict)
    issue_counts: dict[str, int] = Field(default_factory=dict)
    issues: list[ImportHealthIssue] = Field(default_factory=list)
    latest_import_batches: list[ImportBatchSummary] = Field(default_factory=list)
