from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from scenario_db.db.base import Base


class WriteBatch(Base):
    __tablename__ = "write_batches"
    __table_args__ = (
        CheckConstraint(
            "kind in ('scenario.variant_overlay', 'scenario.pipeline_patch', 'scenario.import_bundle')",
            name="ck_write_batches_kind",
        ),
        CheckConstraint(
            "status in ('staged', 'validated', 'validation_failed', 'diff_ready', 'applied')",
            name="ck_write_batches_status",
        ),
        Index("idx_write_batches_updated_at", "updated_at"),
    )

    id                 = Column(Text, primary_key=True)
    kind               = Column(Text, nullable=False)
    target_id          = Column(Text)
    status             = Column(Text, nullable=False)
    actor              = Column(Text)
    note               = Column(Text)
    raw_payload        = Column(JSONB, nullable=False)
    normalized_payload = Column(JSONB)
    validation_result  = Column(JSONB)
    diff_result        = Column(JSONB)
    applied_refs       = Column(JSONB)
    created_at         = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at         = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class WriteEvent(Base):
    __tablename__ = "write_events"
    __table_args__ = (
        CheckConstraint(
            "action in ('stage', 'validate', 'diff', 'apply')",
            name="ck_write_events_action",
        ),
    )

    id         = Column(Text, primary_key=True)
    batch_id   = Column(Text, ForeignKey("write_batches.id"), nullable=False)
    action     = Column(Text, nullable=False)
    actor      = Column(Text)
    result     = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
