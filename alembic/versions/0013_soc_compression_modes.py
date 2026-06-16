"""soc compression mode catalog

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("soc_platforms", sa.Column("compression_modes", JSONB))


def downgrade() -> None:
    op.drop_column("soc_platforms", "compression_modes")
