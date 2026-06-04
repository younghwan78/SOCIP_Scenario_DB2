"""soc dvfs tables

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "soc_dvfs_tables",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("schema_version", sa.Text, nullable=False),
        sa.Column("soc_ref", sa.Text, sa.ForeignKey("soc_platforms.id"), nullable=False),
        sa.Column("dvfs_version", sa.Integer, nullable=False),
        sa.Column("evt_hint", sa.Text),
        sa.Column("source", JSONB),
        sa.Column("domains", JSONB, nullable=False),
        sa.Column("compatibility_scope", sa.Text, nullable=False),
        sa.Column("source_project_ref", sa.Text),
        sa.Column("domain_schema_hash", sa.Text),
        sa.Column("yaml_sha256", sa.Text, nullable=False),
        sa.UniqueConstraint("soc_ref", "dvfs_version", name="uq_soc_dvfs_tables_soc_version"),
    )
    op.create_index("idx_soc_dvfs_tables_soc", "soc_dvfs_tables", ["soc_ref"])
    op.create_index("idx_soc_dvfs_tables_soc_version", "soc_dvfs_tables", ["soc_ref", "dvfs_version"])


def downgrade() -> None:
    op.drop_index("idx_soc_dvfs_tables_soc_version", table_name="soc_dvfs_tables")
    op.drop_index("idx_soc_dvfs_tables_soc", table_name="soc_dvfs_tables")
    op.drop_table("soc_dvfs_tables")
