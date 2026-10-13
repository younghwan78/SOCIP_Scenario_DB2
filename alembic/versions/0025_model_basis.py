"""model basis (예측 기준): named, immutable bundle of config profile / power params / DVFS / engine per project

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0025"
down_revision = "0024_prediction_collaboration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_bases",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_ref", sa.Text(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("config_profile_ref", sa.Text()),
        sa.Column("power_params_ref", sa.Text()),
        sa.Column("dvfs_table_ref", sa.Text()),
        sa.Column("engine_rev", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("input_stamp", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("parent_ref", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("trial", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("activated_by", sa.Text()),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("project_ref", "seq", name="uq_model_bases_project_seq"),
        sa.CheckConstraint("status in ('draft', 'active', 'retired')", name="ck_model_bases_status"),
    )
    op.create_index("ix_model_bases_project_ref", "model_bases", ["project_ref"])
    # one active basis per project
    op.create_index("uq_model_bases_active", "model_bases", ["project_ref"], unique=True,
                    postgresql_where=sa.text("status = 'active'"))


def downgrade() -> None:
    op.drop_index("uq_model_bases_active", table_name="model_bases")
    op.drop_index("ix_model_bases_project_ref", table_name="model_bases")
    op.drop_table("model_bases")
