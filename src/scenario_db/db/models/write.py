from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from scenario_db.db.base import Base


class WriteBatch(Base):
    __tablename__ = "write_batches"

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

    id         = Column(Text, primary_key=True)
    batch_id   = Column(Text, ForeignKey("write_batches.id"), nullable=False)
    action     = Column(Text, nullable=False)
    actor      = Column(Text)
    result     = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
