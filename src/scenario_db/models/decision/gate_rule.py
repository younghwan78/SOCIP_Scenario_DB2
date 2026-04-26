from __future__ import annotations

from typing import Literal

from pydantic import Field

from scenario_db.models.common import BaseScenarioModel, DocumentId, SchemaVersion, Severity
from scenario_db.models.decision.common import GateResultStatus


class GateRuleMetadata(BaseScenarioModel):
    name: str
    category: list[str] = Field(default_factory=list)
    severity: Severity | None = None


class GateTrigger(BaseScenarioModel):
    events: list[str] = Field(default_factory=list)


class GateAppliesTo(BaseScenarioModel):
    # Sugar DSL — e.g. {"variant.severity": {"$in": ["heavy", "critical"]}}
    # 런타임 평가기가 해석; Pydantic에서는 dict로만 저장
    match: dict[str, object] | None = None


class GateCondition(BaseScenarioModel):
    # Sugar DSL — e.g. {"evidence.resolution_result.overall_feasibility": {"$in": ["infeasible"]}}
    match: dict[str, object] | None = None


class GateEscalation(BaseScenarioModel):
    notify: list[str] = Field(default_factory=list)


class GateAction(BaseScenarioModel):
    gate_result: GateResultStatus
    message_template: str | None = None
    required_resolution: str | None = None
    escalation: GateEscalation | None = None


class GateRule(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["decision.gate_rule"]
    metadata: GateRuleMetadata
    trigger: GateTrigger
    applies_to: GateAppliesTo | None = None
    condition: GateCondition
    action: GateAction
