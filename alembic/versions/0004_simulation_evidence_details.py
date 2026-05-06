"""simulation evidence detail fields

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("dma_breakdown", JSONB))
    op.add_column("evidence", sa.Column("timing_breakdown", JSONB))
    op.add_column("evidence", sa.Column("dvfs_breakdown", JSONB))
    op.add_column("evidence", sa.Column("timeline_events", JSONB))
    op.add_column("evidence", sa.Column("vdd_power", JSONB))
    op.add_column("evidence", sa.Column("params_hash", sa.Text))
    op.create_index("ix_evidence_params_hash", "evidence", ["params_hash"])


def downgrade() -> None:
    op.drop_index("ix_evidence_params_hash", table_name="evidence")
    op.drop_column("evidence", "params_hash")
    op.drop_column("evidence", "vdd_power")
    op.drop_column("evidence", "timeline_events")
    op.drop_column("evidence", "dvfs_breakdown")
    op.drop_column("evidence", "timing_breakdown")
    op.drop_column("evidence", "dma_breakdown")
