"""derived variant overlay support

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scenario_variants", sa.Column("design_conditions_override", JSONB))


def downgrade() -> None:
    op.drop_column("scenario_variants", "design_conditions_override")
