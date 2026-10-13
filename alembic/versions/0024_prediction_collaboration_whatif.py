"""Prediction notes, scoped comments and frozen what-if experiments.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prediction_notes",
        sa.Column("prediction_ref", sa.Text(), sa.ForeignKey("predictions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("purpose", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("assumptions", sa.Text(), nullable=False, server_default=""),
        sa.Column("conclusion", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("revision > 0", name="ck_prediction_note_revision"),
    )
    op.create_table(
        "prediction_comments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("prediction_ref", sa.Text(), sa.ForeignKey("predictions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_ref", sa.Text()),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("prediction_ref", "id", name="uq_prediction_comment_scope"),
        sa.ForeignKeyConstraint(
            ["prediction_ref", "parent_ref"], ["prediction_comments.prediction_ref", "prediction_comments.id"],
            name="fk_prediction_comment_parent_scope", ondelete="CASCADE",
        ),
    )
    op.create_index("idx_prediction_comment_order", "prediction_comments", ["prediction_ref", "created_at", "id"])
    op.create_table(
        "whatif_experiments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_ref", sa.Text(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("scenario_ref", sa.Text(), sa.ForeignKey("scenarios.id"), nullable=False),
        sa.Column("variant_ref", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("assumptions", sa.Text()),
        sa.Column("conclusion", sa.Text()),
        sa.Column("query", sa.Text()),
        sa.Column("visibility", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("baseline_hash", sa.Text(), nullable=False),
        sa.Column("condition_hash", sa.Text(), nullable=False),
        sa.Column("preview_request", JSONB(), nullable=False),
        sa.Column("normalized_condition", JSONB(), nullable=False),
        sa.Column("result", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("visibility in ('private', 'shared')", name="ck_whatif_visibility"),
    )
    op.create_index("idx_whatif_scope", "whatif_experiments", ["project_ref", "scenario_ref", "variant_ref", "created_at"])
    op.create_index("idx_whatif_owner", "whatif_experiments", ["created_by", "created_at"])


def downgrade() -> None:
    op.drop_table("whatif_experiments")
    op.drop_table("prediction_comments")
    op.drop_table("prediction_notes")
