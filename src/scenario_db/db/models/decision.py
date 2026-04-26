from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from scenario_db.db.base import Base


class GateRule(Base):
    __tablename__ = "gate_rules"

    id             = Column(Text, primary_key=True)
    schema_version = Column(Text, nullable=False)
    metadata_      = Column("metadata", JSONB, nullable=False)
    trigger        = Column(JSONB, nullable=False)
    applies_to     = Column(JSONB)
    condition      = Column(JSONB, nullable=False)
    action         = Column(JSONB, nullable=False)
    yaml_sha256    = Column(Text, nullable=False)


class Issue(Base):
    __tablename__ = "issues"

    id             = Column(Text, primary_key=True)
    schema_version = Column(Text, nullable=False)
    metadata_      = Column("metadata", JSONB, nullable=False)
    affects        = Column(JSONB)
    affects_ip     = Column(JSONB)
    pmu_signature  = Column(JSONB)
    resolution     = Column(JSONB)
    yaml_sha256    = Column(Text, nullable=False)


class Waiver(Base):
    __tablename__ = "waivers"

    id                      = Column(Text, primary_key=True)
    yaml_sha256             = Column(Text, nullable=False)
    title                   = Column(Text, nullable=False)
    issue_ref               = Column(Text, ForeignKey("issues.id"))
    scope                   = Column(JSONB, nullable=False)
    justification           = Column(Text)
    status                  = Column(Text, nullable=False)
    # Track 1: Author Claim
    approver_claim          = Column(Text, nullable=False)
    claim_at                = Column(Date)
    # Track 2: Git
    git_commit_sha          = Column(Text)
    git_commit_author_email = Column(Text)
    git_signed              = Column(Boolean)
    # Track 3: Server (API 주입)
    approved_by_auth        = Column(Text)
    auth_method             = Column(Text)
    auth_timestamp          = Column(DateTime(timezone=True))
    auth_session_id         = Column(Text)
    approved_at             = Column(Date)
    expires_on              = Column(Date)


class WaiverAuditLog(Base):
    __tablename__ = "waiver_audit_log"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    waiver_id    = Column(Text, nullable=False)
    action       = Column(Text, nullable=False)   # created | approved | revoked | expired
    actor        = Column(Text)
    actor_method = Column(Text)
    timestamp    = Column(DateTime(timezone=True), server_default=func.now())
    before_state = Column(JSONB)
    after_state  = Column(JSONB)


class Review(Base):
    __tablename__ = "reviews"

    id                      = Column(Text, primary_key=True)
    yaml_sha256             = Column(Text, nullable=False)
    scenario_ref            = Column(Text, ForeignKey("scenarios.id"), nullable=False)
    variant_ref             = Column(Text, nullable=False)
    evidence_refs           = Column(JSONB)
    gate_result             = Column(Text)          # PASS | WARN | BLOCK
    auto_checks             = Column(JSONB)
    decision                = Column(Text)
    waiver_ref              = Column(Text, ForeignKey("waivers.id"))
    rationale               = Column(Text)
    review_scope            = Column(JSONB)
    validation_             = Column("validation", JSONB)
    status                  = Column(Text, nullable=False)
    # Triple-Track
    approver_claim          = Column(Text, nullable=False)
    claim_at                = Column(Date)
    git_commit_sha          = Column(Text)
    git_commit_author_email = Column(Text)
    git_signed              = Column(Boolean)
    approved_by_auth        = Column(Text)
    auth_method             = Column(Text)
    auth_timestamp          = Column(DateTime(timezone=True))
    auth_session_id         = Column(Text)


class ReviewAuditLog(Base):
    __tablename__ = "review_audit_log"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    review_id    = Column(Text, nullable=False)
    action       = Column(Text, nullable=False)
    actor        = Column(Text)
    actor_method = Column(Text)
    timestamp    = Column(DateTime(timezone=True), server_default=func.now())
    before_state = Column(JSONB)
    after_state  = Column(JSONB)
