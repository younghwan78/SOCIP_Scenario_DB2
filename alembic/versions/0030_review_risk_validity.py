"""review_risks: validity (RISK-01) and rule-generated check items

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-18
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("review_risks", sa.Column("validity", sa.Text()))
    op.add_column("review_risks", sa.Column("checks", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))


def downgrade() -> None:
    op.drop_column("review_risks", "checks")
    op.drop_column("review_risks", "validity")
