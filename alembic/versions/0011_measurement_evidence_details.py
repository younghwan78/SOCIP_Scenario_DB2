"""measurement evidence detail fields

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("project_ref", sa.Text, sa.ForeignKey("projects.id")))
    op.add_column("evidence", sa.Column("measured_at", sa.DateTime(timezone=True)))
    op.add_column("evidence", sa.Column("derived_from", JSONB))
    op.add_column("evidence", sa.Column("cpu_breakdown", JSONB))
    op.add_column("evidence", sa.Column("sw_task_timing", JSONB))
    op.create_index("ix_evidence_project_ref", "evidence", ["project_ref"])
    op.create_index("ix_evidence_measured_at", "evidence", ["measured_at"])


def downgrade() -> None:
    op.drop_index("ix_evidence_measured_at", table_name="evidence")
    op.drop_index("ix_evidence_project_ref", table_name="evidence")
    op.drop_column("evidence", "sw_task_timing")
    op.drop_column("evidence", "cpu_breakdown")
    op.drop_column("evidence", "derived_from")
    op.drop_column("evidence", "measured_at")
    op.drop_column("evidence", "project_ref")
