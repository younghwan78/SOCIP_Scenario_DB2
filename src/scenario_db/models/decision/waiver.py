from __future__ import annotations

from typing import Literal

from pydantic import Field

from scenario_db.models.common import BaseScenarioModel, DocumentId, SchemaVersion
from scenario_db.models.decision.common import Attestation, MatchCondition, MatchRule
from scenario_db.models.decision.review import WaiverStatus


class WaiverVariantScope(BaseScenarioModel):
    scenario_ref: DocumentId
    match_rule: MatchRule | None = None


class WaiverExecutionScope(BaseScenarioModel):
    # Waiver execution_scope는 AST MatchCondition 리스트 (Review의 flat dict와 다름)
    all: list[MatchCondition] = Field(default_factory=list)


class WaiverScope(BaseScenarioModel):
    variant_scope: WaiverVariantScope | None = None
    execution_scope: WaiverExecutionScope | None = None


class Waiver(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["decision.waiver"]
    title: str
    issue_ref: DocumentId
    scope: WaiverScope
    justification: str | None = None
    attestation: Attestation
    approved_at: str | None = None
    expires_on: str | None = None
    status: WaiverStatus
    review_cycle: str | None = None
    next_review_due: str | None = None
