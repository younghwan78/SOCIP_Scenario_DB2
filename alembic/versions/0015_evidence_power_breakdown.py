"""evidence power breakdown (ip / memory / cpu buckets + power model stamp)

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("power_breakdown", JSONB))


def downgrade() -> None:
    op.drop_column("evidence", "power_breakdown")
