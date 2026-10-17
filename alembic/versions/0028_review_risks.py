"""review_risks: project risk register for the review report (RPT-04)

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_risks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_ref", sa.Text(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("risk_key", sa.Text(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("affected", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("mitigation", sa.Text()),
        sa.Column("owner", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("note", sa.Text()),
        sa.Column("auto_state", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.Text()),
        sa.Column("last_report_ref", sa.Text()),
        sa.Column("history", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.UniqueConstraint("project_ref", "risk_key", name="uq_review_risk_key"),
        sa.UniqueConstraint("project_ref", "seq", name="uq_review_risk_seq"),
        sa.CheckConstraint("severity in ('critical', 'high', 'medium', 'info')", name="ck_review_risk_severity"),
        sa.CheckConstraint("status in ('open', 'watch', 'mitigating', 'accepted', 'closed')", name="ck_review_risk_status"),
        sa.CheckConstraint("auto_state in ('active', 'resolve_candidate', 'manual')", name="ck_review_risk_auto_state"),
    )
    op.create_index("ix_review_risks_project_ref", "review_risks", ["project_ref"])


def downgrade() -> None:
    op.drop_index("ix_review_risks_project_ref", table_name="review_risks")
    op.drop_table("review_risks")
