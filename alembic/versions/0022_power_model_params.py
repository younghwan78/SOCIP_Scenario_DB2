"""power model params (SoC-scoped coefficients: ref V/fps, BW model, CPU, calibration lineage)

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "power_model_params",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("soc_ref", sa.Text(), sa.ForeignKey("soc_platforms.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("params", JSONB, nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("yaml_sha256", sa.Text(), nullable=False),
        sa.UniqueConstraint("soc_ref", "version", name="uq_power_model_params_soc_version"),
        sa.CheckConstraint("status in ('draft', 'approved')", name="ck_power_model_params_status"),
        sa.CheckConstraint("version >= 1", name="ck_power_model_params_version"),
    )
    op.create_index("ix_power_model_params_soc_ref", "power_model_params", ["soc_ref"])


def downgrade() -> None:
    op.drop_index("ix_power_model_params_soc_ref", table_name="power_model_params")
    op.drop_table("power_model_params")
