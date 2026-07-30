"""evidence metric observations

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("metric_observations", JSONB))


def downgrade() -> None:
    op.drop_column("evidence", "metric_observations")
