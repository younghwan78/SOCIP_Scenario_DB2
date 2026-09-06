"""sim config profiles (per-project agreed simulation settings)

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sim_config_profiles",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("project_ref", sa.Text(), sa.ForeignKey("projects.id"), index=True),
        sa.Column("soc_ref", sa.Text(), sa.ForeignKey("soc_platforms.id"), index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("approved_by", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("run_config", JSONB, nullable=False),
        sa.Column("rail_domain_map", JSONB),
        sa.Column("notes", sa.Text()),
        sa.Column("yaml_sha256", sa.Text(), nullable=False),
        sa.CheckConstraint("status in ('draft', 'approved')", name="ck_simcfg_status"),
    )


def downgrade() -> None:
    op.drop_table("sim_config_profiles")
