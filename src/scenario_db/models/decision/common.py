from __future__ import annotations

from enum import StrEnum
from typing import TypeAlias

from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel


# ---------------------------------------------------------------------------
# Triple-Track Attestation (§18)
# ---------------------------------------------------------------------------

class AuthMethod(StrEnum):
    sso = "sso"
    mfa = "mfa"
    signed_jwt = "signed_jwt"


class GitAttestation(BaseScenarioModel):
    commit_sha: str | None = None
    commit_author_email: str | None = None
    signed: bool | None = None


class ServerAttestation(BaseScenarioModel):
    approved_by_auth: str | None = None      # API 서버 주입 — 초기엔 null
    auth_method: AuthMethod | None = None
    auth_timestamp: str | None = None
    auth_session_id: str | None = None
    ip_address: str | None = None


class Attestation(BaseScenarioModel):
    approver_claim: str                      # Track 1: YAML 작성자 선언
    claim_at: str                            # ISO 8601 날짜
    git_attestation: GitAttestation | None = None     # Track 2
    server_attestation: ServerAttestation | None = None  # Track 3


# ---------------------------------------------------------------------------
# Matcher DSL — Canonical AST (§19)
# ---------------------------------------------------------------------------

class MatchOp(StrEnum):
    eq = "eq"
    ne = "ne"
    in_ = "in"          # Python 예약어 우회: value는 "in", Pydantic이 `op: in` 파싱 정상 동작
    not_in = "not_in"
    gt = "gt"
    gte = "gte"
    lt = "lt"
    lte = "lte"
    matches = "matches"
    exists = "exists"
    between = "between"


MatchValue: TypeAlias = (
    str | int | float | bool | list[str | int | float | bool]
)


class MatchCondition(BaseScenarioModel):
    # subject 필드: axis / sw_feature / sw_component / sw_version / ip 중 정확히 하나만
    axis: str | None = None
    sw_feature: str | None = None
    sw_component: str | None = None
    sw_version: str | None = None
    ip: str | None = None       # e.g. "ISP.TNR"
    field: str | None = None    # ip 조건 시 세부 필드 (e.g. "mode")
    op: MatchOp
    value: MatchValue

    @model_validator(mode="after")
    def _validate_single_subject(self) -> MatchCondition:
        subjects = [self.axis, self.sw_feature, self.sw_component, self.sw_version, self.ip]
        active = [s for s in subjects if s is not None]
        if len(active) != 1:
            raise ValueError(
                f"MatchCondition must have exactly one subject field set "
                f"(axis/sw_feature/sw_component/sw_version/ip). Got {len(active)}."
            )
        return self

    @model_validator(mode="after")
    def _validate_op_value_compat(self) -> MatchCondition:
        if self.op in (MatchOp.in_, MatchOp.not_in) and not isinstance(self.value, list):
            raise ValueError(f"Operator '{self.op}' requires value to be a list.")
        if self.op == MatchOp.between:
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError(
                    "Operator 'between' requires value to be a list of exactly two items."
                )
        return self


class SwConditions(BaseScenarioModel):
    all: list[MatchCondition] = Field(default_factory=list)
    any: list[MatchCondition] = Field(default_factory=list)
    none: list[MatchCondition] = Field(default_factory=list)


class MatchScope(BaseScenarioModel):
    project_ref: str | None = None          # "*" 와일드카드 허용 → str (not DocumentId)
    soc_ref: str | None = None
    sw_baseline_family: str | None = None
    sw_baseline_ref: str | None = None


class MatchRule(BaseScenarioModel):
    scope: MatchScope | None = None
    all: list[MatchCondition] = Field(default_factory=list)
    any: list[MatchCondition] = Field(default_factory=list)
    none: list[MatchCondition] = Field(default_factory=list)
    sw_conditions: SwConditions | None = None


# ---------------------------------------------------------------------------
# Shared gate result status (Review + GateRule)
# ---------------------------------------------------------------------------

class GateResultStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"
