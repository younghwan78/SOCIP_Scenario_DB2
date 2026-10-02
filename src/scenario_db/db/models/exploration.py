"""Architecture exploration runs, promoted predictions and review reports."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Text, UniqueConstraint, func, text
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
