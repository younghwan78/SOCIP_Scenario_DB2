from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from scenario_db.models.common import (
    BaseScenarioModel,
    DocumentId,
    FeatureFlagValue,
    ViolationAction,
)


# ---------------------------------------------------------------------------
# Violation records — typed per context (HW vs SW separated)
# ---------------------------------------------------------------------------

class HwViolation(BaseScenarioModel):
    requirement: str
    requested: float | int | str | None = None
    provided: float | int | str | None = None
    action_taken: ViolationAction
    gap_pct: float | None = None
    reason: str | None = None


class SwViolation(BaseScenarioModel):
    feature: str
    required: FeatureFlagValue
    actual: FeatureFlagValue
    action_taken: ViolationAction
    emulation_note: str | None = None


# ---------------------------------------------------------------------------
# Feature / HAL compatibility checks
# ---------------------------------------------------------------------------

class FeatureCheck(BaseScenarioModel):
    feature: str
    required: FeatureFlagValue
    actual: FeatureFlagValue
    status: Literal["PASS", "FAIL"]


class HalCompatibilityCheck(BaseScenarioModel):
    required_min: str
    actual: str
    status: Literal["PASS", "FAIL"]


# ---------------------------------------------------------------------------
# HW / SW resolution results
# ---------------------------------------------------------------------------

class HwNodeResolution(BaseScenarioModel):
    requested: dict[str, float | int | str] = Field(default_factory=dict)
    matched_mode: str
    capability_max: float | int | None = None
    headroom: dict[str, float | int | str] | None = None
    violations: list[HwViolation] = Field(default_factory=list)


class SwResolution(BaseScenarioModel):
    profile_ref: DocumentId
    required_features_check: list[FeatureCheck] = Field(default_factory=list)
    hal_compatibility: dict[str, HalCompatibilityCheck] | None = None
    violations: list[SwViolation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Aggregated result
# ---------------------------------------------------------------------------

class ViolationSummary(BaseScenarioModel):
    total: int
    fail_fast: int = 0
    warn_and_cap: int = 0
    warn_and_emulate: int = 0


class OverallFeasibility(StrEnum):
    production_ready = "production_ready"
    exploration_only = "exploration_only"
    infeasible = "infeasible"
    research_mode = "research_mode"


class ResolutionResult(BaseScenarioModel):
    hw_resolution: dict[str, HwNodeResolution] = Field(default_factory=dict)
    sw_resolution: SwResolution | None = None
    overall_feasibility: OverallFeasibility
    # Top-level violations removed: HW violations live in hw_resolution[node].violations,
    # SW violations live in sw_resolution.violations — already fully typed there.
    violation_summary: ViolationSummary | None = None
