from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from scenario_db.db.models.decision import GateRule, Issue, Review, Waiver
from scenario_db.models.decision.gate_rule import GateRule as PydanticGateRule
from scenario_db.models.decision.issue import Issue as PydanticIssue
from scenario_db.models.decision.review import Review as PydanticReview
from scenario_db.models.decision.waiver import Waiver as PydanticWaiver


def upsert_gate_rule(raw: dict, sha256: str, session: Session) -> None:
    obj = PydanticGateRule.model_validate(raw)
    row = session.get(GateRule, obj.id) or GateRule(id=obj.id)
    if row.yaml_sha256 == sha256:
        return
    row.schema_version = obj.schema_version
    row.metadata_      = obj.metadata.model_dump(exclude_none=True)
    row.trigger        = obj.trigger.model_dump(exclude_none=True)
    row.applies_to     = obj.applies_to.model_dump(exclude_none=True) if obj.applies_to else None
    row.condition      = obj.condition.model_dump(exclude_none=True)
    row.action         = obj.action.model_dump(exclude_none=True)
    row.yaml_sha256    = sha256
    session.add(row)


def upsert_issue(raw: dict, sha256: str, session: Session) -> None:
    obj = PydanticIssue.model_validate(raw)
    row = session.get(Issue, obj.id) or Issue(id=obj.id)
    if row.yaml_sha256 == sha256:
        return
    row.schema_version = obj.schema_version
    row.metadata_      = obj.metadata.model_dump(exclude_none=True)
    row.affects        = [a.model_dump(by_alias=True, exclude_none=True) for a in obj.affects]
    row.affects_ip     = [a.model_dump(exclude_none=True) for a in obj.affects_ip]
    row.pmu_signature  = [p.model_dump(exclude_none=True) for p in obj.pmu_signature]
    row.resolution     = obj.resolution.model_dump(exclude_none=True) if obj.resolution else None
    row.yaml_sha256    = sha256
    session.add(row)


def upsert_waiver(raw: dict, sha256: str, session: Session) -> None:
    obj = PydanticWaiver.model_validate(raw)
    row = session.get(Waiver, obj.id) or Waiver(id=obj.id)
    if row.yaml_sha256 == sha256:
        return
    att = obj.attestation
    git = att.git_attestation
    srv = att.server_attestation
    row.yaml_sha256             = sha256
    row.title                   = obj.title
    row.issue_ref               = str(obj.issue_ref)
    row.scope                   = obj.scope.model_dump(by_alias=True, exclude_none=True)
    row.justification           = obj.justification
    row.status                  = str(obj.status)
    row.approver_claim          = att.approver_claim
    row.claim_at                = _parse_date(att.claim_at)
    row.git_commit_sha          = git.commit_sha if git else None
    row.git_commit_author_email = git.commit_author_email if git else None
    row.git_signed              = git.signed if git else None
    row.approved_by_auth        = srv.approved_by_auth if srv else None
    row.auth_method             = str(srv.auth_method) if (srv and srv.auth_method) else None
    row.auth_session_id         = srv.auth_session_id if srv else None
    row.approved_at             = _parse_date(obj.approved_at) if obj.approved_at else None
    row.expires_on              = _parse_date(obj.expires_on) if obj.expires_on else None
    session.add(row)


def upsert_review(raw: dict, sha256: str, session: Session) -> None:
    obj = PydanticReview.model_validate(raw)
    row = session.get(Review, obj.id) or Review(id=obj.id)
    if row.yaml_sha256 == sha256:
        return
    att = obj.attestation
    git = att.git_attestation
    srv = att.server_attestation
    row.yaml_sha256             = sha256
    row.scenario_ref            = str(obj.scenario_ref)
    row.variant_ref             = obj.variant_ref
    row.evidence_refs           = list(obj.evidence_refs)
    row.gate_result             = str(obj.gate_result)
    row.auto_checks             = [c.model_dump(exclude_none=True) for c in obj.auto_checks]
    row.decision                = str(obj.decision)
    row.waiver_ref              = str(obj.waiver_ref) if obj.waiver_ref else None
    row.rationale               = obj.rationale
    row.review_scope            = obj.review_scope.model_dump(exclude_none=True) if obj.review_scope else None
    row.validation_             = obj.validation.model_dump(exclude_none=True) if obj.validation else None
    row.status                  = "approved"   # 모든 demo 데이터는 approved 상태
    row.approver_claim          = att.approver_claim
    row.claim_at                = _parse_date(att.claim_at)
    row.git_commit_sha          = git.commit_sha if git else None
    row.git_commit_author_email = git.commit_author_email if git else None
    row.git_signed              = git.signed if git else None
    row.approved_by_auth        = srv.approved_by_auth if srv else None
    row.auth_method             = str(srv.auth_method) if (srv and srv.auth_method) else None
    row.auth_session_id         = srv.auth_session_id if srv else None
    session.add(row)


def _parse_date(value: str | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)
