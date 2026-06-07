"""soc cdgm profiles

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "soc_cdgm_profiles",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("schema_version", sa.Text, nullable=False),
        sa.Column("soc_ref", sa.Text, sa.ForeignKey("soc_platforms.id"), nullable=False),
        sa.Column("profile_version", sa.Integer, nullable=False),
        sa.Column("evt_hint", sa.Text),
        sa.Column("source", JSONB),
        sa.Column("compatibility_scope", sa.Text, nullable=False),
        sa.Column("source_project_ref", sa.Text),
        sa.Column("domain_schema_hash", sa.Text),
        sa.Column("role_overrides", JSONB, nullable=False),
        sa.Column("selection_policy", JSONB, nullable=False),
        sa.Column("yaml_sha256", sa.Text, nullable=False),
        sa.UniqueConstraint("soc_ref", "profile_version", name="uq_soc_cdgm_profiles_soc_version"),
        sa.CheckConstraint("profile_version >= 0", name="ck_soc_cdgm_profiles_profile_version_nonnegative"),
        sa.CheckConstraint("compatibility_scope in ('soc', 'project')", name="ck_soc_cdgm_profiles_scope"),
    )
    op.create_index("idx_soc_cdgm_profiles_soc", "soc_cdgm_profiles", ["soc_ref"])
    op.create_index("idx_soc_cdgm_profiles_soc_version", "soc_cdgm_profiles", ["soc_ref", "profile_version"])


def downgrade() -> None:
    op.drop_index("idx_soc_cdgm_profiles_soc_version", table_name="soc_cdgm_profiles")
    op.drop_index("idx_soc_cdgm_profiles_soc", table_name="soc_cdgm_profiles")
    op.drop_table("soc_cdgm_profiles")
