"""Add simulation external device and topology details."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("external_devices", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("evidence", sa.Column("topology_order", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("evidence", "topology_order")
    op.drop_column("evidence", "external_devices")
