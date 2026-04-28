from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


WriteKind = Literal["scenario.variant_overlay", "scenario.pipeline_patch"]


class StageWriteRequest(BaseModel):
    kind: WriteKind
    payload: dict[str, Any]
    actor: str | None = None
    note: str | None = None


class WriteBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    target_id: str | None = None
    status: str
    actor: str | None = None
    note: str | None = None
    raw_payload: dict[str, Any]
    normalized_payload: dict[str, Any] | None = None
    validation_result: dict[str, Any] | None = None
    diff_result: dict[str, Any] | None = None
    applied_refs: dict[str, Any] | None = None


class StageWriteResponse(BaseModel):
    batch_id: str
    status: str
    target_id: str | None = None


class ValidationIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    path: str | None = None


class ValidateWriteResponse(BaseModel):
    batch_id: str
    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    normalized_payload: dict[str, Any] | None = None


class DiffEntry(BaseModel):
    field: str
    change: Literal["add", "remove", "modify", "unchanged"]
    before: Any = None
    after: Any = None


class DiffPreviewResponse(BaseModel):
    batch_id: str
    target_id: str
    operation: Literal["create", "update"]
    changes: list[DiffEntry] = Field(default_factory=list)
    impact: dict[str, Any] | None = None


class ApplyWriteResponse(BaseModel):
    batch_id: str
    status: str
    applied_refs: dict[str, Any]
