from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from scenario_db.models.common import BaseScenarioModel, DocumentId, SchemaVersion, Severity
from scenario_db.models.decision.common import MatchRule


class IssueStatus(StrEnum):
    open = "open"
    resolved = "resolved"
    wontfix = "wontfix"
    deferred = "deferred"


class RootCauseSwChange(BaseScenarioModel):
    area: str
    description: str


class SwRegression(BaseScenarioModel):
    discovered_in_sw: DocumentId
    last_good_sw: DocumentId | None = None
    root_cause_sw_change: RootCauseSwChange | None = None
    fixed_in_sw: DocumentId | None = None


class IssueMetadata(BaseScenarioModel):
    title: str
    severity: Severity
    status: IssueStatus
    discovered_in: DocumentId
    discovered_at: str
    sw_regression: SwRegression | None = None


class AffectsItem(BaseScenarioModel):
    scenario_ref: DocumentId
    match_rule: MatchRule | None = None


class IssueAffectsIpItem(BaseScenarioModel):
    ip_ref: DocumentId
    submodule: str | None = None    # InstanceId 형식 (ISP.TNR), 선택적이라 str


class PmuSignatureItem(BaseScenarioModel):
    counter: str
    threshold: str


class IssueResolution(BaseScenarioModel):
    fix_commit: str | None = None
    fix_sw_ref: DocumentId | None = None
    fix_description: str | None = None
    verified_in_evidence: DocumentId | None = None
    fix_date: str | None = None


class Issue(BaseScenarioModel):
    id: DocumentId
    schema_version: SchemaVersion
    kind: Literal["decision.issue"]
    metadata: IssueMetadata
    affects: list[AffectsItem] = Field(default_factory=list)
    affects_ip: list[IssueAffectsIpItem] = Field(default_factory=list)
    pmu_signature: list[PmuSignatureItem] = Field(default_factory=list)
    resolution: IssueResolution | None = None
