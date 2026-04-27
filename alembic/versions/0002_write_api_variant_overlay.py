"""write api variant overlay

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("scenario_variants", sa.Column("size_overrides", JSONB))
    op.add_column("scenario_variants", sa.Column("routing_switch", JSONB))
    op.add_column("scenario_variants", sa.Column("topology_patch", JSONB))
    op.add_column("scenario_variants", sa.Column("node_configs", JSONB))
    op.add_column("scenario_variants", sa.Column("buffer_overrides", JSONB))

    op.create_table(
        "write_batches",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("target_id", sa.Text),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("actor", sa.Text),
        sa.Column("note", sa.Text),
        sa.Column("raw_payload", JSONB, nullable=False),
        sa.Column("normalized_payload", JSONB),
        sa.Column("validation_result", JSONB),
        sa.Column("diff_result", JSONB),
        sa.Column("applied_refs", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("idx_write_batches_kind_status", "write_batches", ["kind", "status"])
    op.create_index("idx_write_batches_target", "write_batches", ["target_id"])

    op.create_table(
        "write_events",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("batch_id", sa.Text, sa.ForeignKey("write_batches.id"), nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("actor", sa.Text),
        sa.Column("result", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("idx_write_events_batch", "write_events", ["batch_id"])


def downgrade() -> None:
    op.drop_index("idx_write_events_batch", table_name="write_events")
    op.drop_table("write_events")
    op.drop_index("idx_write_batches_target", table_name="write_batches")
    op.drop_index("idx_write_batches_kind_status", table_name="write_batches")
    op.drop_table("write_batches")

    op.drop_column("scenario_variants", "buffer_overrides")
    op.drop_column("scenario_variants", "node_configs")
    op.drop_column("scenario_variants", "topology_patch")
    op.drop_column("scenario_variants", "routing_switch")
    op.drop_column("scenario_variants", "size_overrides")
