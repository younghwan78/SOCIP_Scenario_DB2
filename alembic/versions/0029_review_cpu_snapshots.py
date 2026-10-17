"""review_cpu_snapshots: CPU what-if results recorded for the project review (CPU-11)

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_cpu_snapshots",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_ref", sa.Text(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("scenario_ref", sa.Text(), nullable=False),
        sa.Column("variant_ref", sa.Text(), nullable=False),
        sa.Column("profile_ref", sa.Text(), nullable=False),
        sa.Column("power_params_ref", sa.Text(), nullable=False),
        sa.Column("base_power_params_ref", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("note", sa.Text()),
        sa.Column("request", JSONB(), nullable=False),
        sa.Column("summary", JSONB(), nullable=False),
        sa.Column("created_by", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status in ('active', 'superseded', 'withdrawn')", name="ck_review_cpu_snapshot_status"),
    )
    op.create_index("ix_review_cpu_snapshots_project_ref", "review_cpu_snapshots", ["project_ref"])
    op.create_index("uq_review_cpu_snapshot_active", "review_cpu_snapshots", ["project_ref", "scenario_ref", "variant_ref"],
                    unique=True, postgresql_where=sa.text("status = 'active'"))


def downgrade() -> None:
    op.drop_index("uq_review_cpu_snapshot_active", table_name="review_cpu_snapshots")
    op.drop_index("ix_review_cpu_snapshots_project_ref", table_name="review_cpu_snapshots")
    op.drop_table("review_cpu_snapshots")
