"""simulation calculation trace

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-09 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("calculation_trace", JSONB))


def downgrade() -> None:
    op.drop_column("evidence", "calculation_trace")
