"""review_risks: priority (RISK-02), due date / closure evidence / decision flag (RISK-03)

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("review_risks", sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("review_risks", sa.Column("decision_needed", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("review_risks", sa.Column("due_date", sa.Date()))
    op.add_column("review_risks", sa.Column("closure_evidence", sa.Text()))


def downgrade() -> None:
    for c in ("closure_evidence", "due_date", "decision_needed", "priority"):
        op.drop_column("review_risks", c)
