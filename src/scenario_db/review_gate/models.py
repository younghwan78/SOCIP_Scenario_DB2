from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class RuleCheckResult(BaseModel):
    rule_id: str
    status: Literal["PASS", "WARN", "BLOCK"] = "PASS"
    message: str | None = None


class IssueMatchResult(BaseModel):
    issue_id: str
    title: str
    severity: str | None = None
    status: str | None = None
    matched_by: str = "match_rule"


class WaiverMatchResult(BaseModel):
    waiver_id: str
    issue_ref: str | None = None
    status: str
    applies: bool = False


class GateExecutionResult(BaseModel):
    scenario_id: str
    variant_id: str
    status: Literal["PASS", "WARN", "BLOCK", "WAIVER_REQUIRED"]
    matched_rules: list[RuleCheckResult] = []
    matched_issues: list[IssueMatchResult] = []
    applicable_waivers: list[WaiverMatchResult] = []
    missing_waivers: list[str] = []
    evidence_refs: list[str] = []
    resolver_warnings: list[str] = []
    summary: dict = {}

