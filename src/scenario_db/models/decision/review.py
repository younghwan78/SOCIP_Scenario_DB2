from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import ConfigDict, Field

from scenario_db.models.common import BaseScenarioModel, DocumentId, SchemaVersion
from scenario_db.models.decision.common import Attestation, GateResultStatus


class WaiverStatus(StrEnum):
    pending_auth = "pending_auth"
    approved = "approved"
    revoked = "revoked"
    expired = "expired"


class ReviewDecision(StrEnum):
    approved = "approved"
    approved_with_waiver = "approved_with_waiver"
    rejected = "rejected"
    conditional_pass = "conditional_pass"


class AutoCheck(BaseScenarioModel):
    rule_ref: DocumentId                     # FK → gate_rules ("rule-" prefix)
    status: GateResultStatus
    detail: str | None = None
    matched_issues: list[DocumentId] = Field(default_factory=list)


class ValidationInfo(BaseScenarioModel):
    last_validated_on: str
    next_review_due: str
    review_cycle: str


class ReviewVariantScope(BaseScenarioModel):
    scenario_ref: DocumentId
    variant_ref: str


class ReviewExecutionScope(BaseScenarioModel):
    # 표준 필드 명시 선언 + 비표준 확장은 extra="allow"로 흡수
    model_config = ConfigDict(extra="allow")
    silicon_rev: str | None = None
    thermal: str | list[str] | None = None
    power_state: str | None = None
    sw_baseline_ref: str | None = None


class ReviewScope(BaseScenarioModel):
    variant_scope: ReviewVariantScope | None = None
    execution_scope: ReviewExecutionScope | None = None


class Review(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["decision.review"]
    scenario_ref: DocumentId
    variant_ref: str
    evidence_refs: list[DocumentId] = Field(default_factory=list)
    gate_result: GateResultStatus
    auto_checks: list[AutoCheck] = Field(default_factory=list)
    attestation: Attestation
    decision: ReviewDecision
    waiver_ref: DocumentId | None = None
    rationale: str | None = None
    validation: ValidationInfo | None = None
    review_scope: ReviewScope | None = None
