"""Architecture exploration runs, promoted predictions and review reports."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from scenario_db.db.base import Base


class ArchExplorationRun(Base):
    __tablename__ = "arch_exploration_runs"

    id = Column(Text, primary_key=True)
    title = Column(Text, nullable=False)
    scenario_type = Column(Text, nullable=False, index=True)
    project_ref = Column(Text, ForeignKey("projects.id"))
    soc_ref = Column(Text, index=True)
    spec = Column(JSONB, nullable=False)
    variants = Column(JSONB, nullable=False)  # per-variant exploration summaries
    errors = Column(JSONB, nullable=False)
    summary = Column(JSONB, nullable=False)  # run-level counts
    dvfs_table_ref = Column(Text)
    engine_rev = Column(Text, nullable=False)
    input_hash = Column(Text, nullable=False)
    created_by = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Prediction(Base):
    """A variant's registered (current) power/BW prediction, promoted from a run case."""

    __tablename__ = "predictions"
    __table_args__ = (
        CheckConstraint("status in ('current', 'superseded')", name="ck_prediction_status"),
        CheckConstraint("selected_by in ('auto', 'user')", name="ck_prediction_selected_by"),
        Index("idx_prediction_variant", "scenario_ref", "variant_ref", "status"),
        Index(
            "uq_prediction_current",
            "scenario_ref",
            "variant_ref",
            unique=True,
            postgresql_where=text("status = 'current'"),
        ),
    )

    id = Column(Text, primary_key=True)
    scenario_ref = Column(Text, ForeignKey("scenarios.id"), nullable=False)
    variant_ref = Column(Text, nullable=False)
    project_ref = Column(Text, ForeignKey("projects.id"))
    status = Column(Text, nullable=False)
    exploration_run_ref = Column(Text, ForeignKey("arch_exploration_runs.id"), nullable=False)
    case_key = Column(Text, nullable=False)
    selection_rule = Column(Text, nullable=False)  # auto:min-power | user:<rank>
    selected_by = Column(Text, nullable=False)
    selected_by_user = Column(Text)
    reason = Column(Text)
    metrics = Column(JSONB, nullable=False)
    input_hash = Column(Text, nullable=False)
    dvfs_table_ref = Column(Text)
    supersedes_ref = Column(Text, ForeignKey("predictions.id"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PredictionNote(Base):
    """Mutable collaboration notes, separate from a prediction's calculated snapshot."""

    __tablename__ = "prediction_notes"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_prediction_note_revision"),
    )

    prediction_ref = Column(Text, ForeignKey("predictions.id", ondelete="CASCADE"), primary_key=True)
    title = Column(Text, nullable=False, server_default="")
    purpose = Column(Text, nullable=False, server_default="")
    description = Column(Text, nullable=False, server_default="")
    assumptions = Column(Text, nullable=False, server_default="")
    conclusion = Column(Text, nullable=False, server_default="")
    tags = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    revision = Column(Integer, nullable=False, server_default=text("1"))
    created_by = Column(Text, nullable=False)
    updated_by = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PredictionComment(Base):
    """Append-only discussion; a reply belongs to the same prediction as its parent."""

    __tablename__ = "prediction_comments"
    __table_args__ = (
        UniqueConstraint("prediction_ref", "id", name="uq_prediction_comment_scope"),
        ForeignKeyConstraint(
            ["prediction_ref", "parent_ref"], ["prediction_comments.prediction_ref", "prediction_comments.id"],
            name="fk_prediction_comment_parent_scope", ondelete="CASCADE",
        ),
        Index("idx_prediction_comment_order", "prediction_ref", "sequence"),
    )

    id = Column(Text, primary_key=True)
    prediction_ref = Column(Text, ForeignKey("predictions.id", ondelete="CASCADE"), nullable=False)
    sequence = Column(BigInteger, Identity(always=True), nullable=False)
    parent_ref = Column(Text)
    body = Column(Text, nullable=False)
    created_by = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ArchReport(Base):
    __tablename__ = "arch_reports"
    __table_args__ = (CheckConstraint("status in ('draft', 'published')", name="ck_arch_report_status"),)

    id = Column(Text, primary_key=True)
    title = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    target_soc_ref = Column(Text, index=True)
    project_ref = Column(Text, ForeignKey("projects.id"))
    scenario_type = Column(Text, nullable=False)
    exploration_run_refs = Column(JSONB, nullable=False)
    dvfs_table_ref = Column(Text)
    engine_rev = Column(Text, nullable=False)
    snapshot = Column(JSONB, nullable=False)  # frozen numbers: report reproducible later
    rendered_html = Column(Text, nullable=False)
    html_sha256 = Column(Text, nullable=False)
    generated_by = Column(Text)
    generated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # [{status, reviewer, note, by, at}] — publishing requires a reviewer and a note
    review_history = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))


POWER_OPTION_STATUSES = ("candidate", "iq_eval", "adopted", "rejected")


class PowerOptionReview(Base):
    """IQ review state of one power-saving option item (knob value or IP mode).

    Options are predicted by combination exploration on top of formal variants; they
    are not variants. ``variant_ref='*'`` applies to every variant of the scenario,
    a concrete variant id overrides it for that variant.
    """

    __tablename__ = "power_option_reviews"
    __table_args__ = (
        CheckConstraint("status in ('candidate', 'iq_eval', 'adopted', 'rejected')",
                        name="ck_power_option_review_status"),
        UniqueConstraint("scenario_ref", "variant_ref", "option_key", name="uq_power_option_review"),
    )

    id = Column(Text, primary_key=True)
    project_ref = Column(Text, ForeignKey("projects.id"), index=True)
    scenario_ref = Column(Text, ForeignKey("scenarios.id"), nullable=False)
    variant_ref = Column(Text, nullable=False)
    option_key = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    note = Column(Text)
    history = Column(JSONB, nullable=False)
    updated_by = Column(Text)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
class ModelBasis(Base):
    """예측 기준: the model inputs a registered number rests on (config profile, power params, DVFS, engine).

    Immutable once created (a change = a new basis with ``parent_ref``); one ``active`` basis per project is the
    default for Timing Budget / exploration / simulation. ``trial`` keeps the dry-run recompute of the project's
    current predictions under a draft basis (P2 promotion).
    """

    __tablename__ = "model_bases"
    __table_args__ = (
        UniqueConstraint("project_ref", "seq", name="uq_model_bases_project_seq"),
        CheckConstraint("status in ('draft', 'active', 'retired')", name="ck_model_bases_status"),
        Index("uq_model_bases_active", "project_ref", unique=True, postgresql_where=text("status = 'active'")),
    )

    id = Column(Text, primary_key=True)
    project_ref = Column(Text, ForeignKey("projects.id"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    code = Column(Text, nullable=False)  # B1, B2 … per project
    title = Column(Text)
    status = Column(Text, nullable=False, default="draft")
    config_profile_ref = Column(Text)
    power_params_ref = Column(Text)  # id@version
    dvfs_table_ref = Column(Text)
    engine_rev = Column(Text, nullable=False)
    content_hash = Column(Text, nullable=False)
    input_stamp = Column(JSONB, nullable=False, default=dict)
    parent_ref = Column(Text)
    notes = Column(Text)
    trial = Column(JSONB, nullable=False, default=dict)
    created_by = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    activated_by = Column(Text)
    activated_at = Column(DateTime(timezone=True))


RISK_SEVERITIES = ("critical", "high", "medium", "info")
RISK_STATUSES = ("open", "watch", "mitigating", "accepted", "closed")
RISK_AUTO_STATES = ("active", "resolve_candidate", "manual")


class ReviewRisk(Base):
    """Risk register of a project review (RPT-04).

    Report generation applies the automatic rules: a firing rule opens or refreshes its row
    (``risk_key`` is stable per project), a row whose rule stopped firing becomes a
    ``resolve_candidate``; owner / status / note are kept by people and never overwritten.
    """

    __tablename__ = "review_risks"
    __table_args__ = (
        UniqueConstraint("project_ref", "risk_key", name="uq_review_risk_key"),
        UniqueConstraint("project_ref", "seq", name="uq_review_risk_seq"),
        CheckConstraint("severity in ('critical', 'high', 'medium', 'info')", name="ck_review_risk_severity"),
        CheckConstraint("status in ('open', 'watch', 'mitigating', 'accepted', 'closed')", name="ck_review_risk_status"),
        CheckConstraint("auto_state in ('active', 'resolve_candidate', 'manual')", name="ck_review_risk_auto_state"),
    )

    id = Column(Text, primary_key=True)
    project_ref = Column(Text, ForeignKey("projects.id"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)  # R-01, R-02 … in order of first appearance
    risk_key = Column(Text, nullable=False)
    rule = Column(Text, nullable=False)
    severity = Column(Text, nullable=False)
    category = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    detail = Column(Text, nullable=False, server_default=text("''"))
    affected = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    mitigation = Column(Text)
    # RISK-01: confirmed · model_limit · input_unverified; checks = what to confirm first (rule-generated)
    validity = Column(Text)
    checks = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # RISK-02 rule priority (higher = check first within a severity); RISK-03 tracking kept by people
    priority = Column(Integer, nullable=False, server_default=text("0"))
    decision_needed = Column(Boolean, nullable=False, server_default=text("false"))
    due_date = Column(Date)
    closure_evidence = Column(Text)
    owner = Column(Text)
    status = Column(Text, nullable=False, server_default=text("'open'"))
    note = Column(Text)
    auto_state = Column(Text, nullable=False, server_default=text("'active'"))
    first_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_by = Column(Text)
    last_report_ref = Column(Text)
    # [{at, by, field, old, new}] — people's edits and automatic state changes
    history = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))


class ReviewCpuSnapshot(Base):
    """CPU what-if result recorded for the project review (CPU-11).

    The server re-runs the SW growth sweep from the stored request, so the report quotes the
    tolerance / OPP step / best distribution computed by the API, never a client's numbers. One
    ``active`` snapshot per (project, scenario, variant); a newer one supersedes it.
    """

    __tablename__ = "review_cpu_snapshots"
    __table_args__ = (
        CheckConstraint("status in ('active', 'superseded', 'withdrawn')", name="ck_review_cpu_snapshot_status"),
        Index("ix_review_cpu_snapshots_project_ref", "project_ref"),
        Index("uq_review_cpu_snapshot_active", "project_ref", "scenario_ref", "variant_ref", unique=True,
              postgresql_where=text("status = 'active'")),
    )

    id = Column(Text, primary_key=True)
    project_ref = Column(Text, ForeignKey("projects.id"), nullable=False)
    scenario_ref = Column(Text, nullable=False)
    variant_ref = Column(Text, nullable=False)
    profile_ref = Column(Text, nullable=False)
    power_params_ref = Column(Text, nullable=False)
    base_power_params_ref = Column(Text)
    status = Column(Text, nullable=False, server_default=text("'active'"))
    note = Column(Text)
    request = Column(JSONB, nullable=False)
    summary = Column(JSONB, nullable=False)
    created_by = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
