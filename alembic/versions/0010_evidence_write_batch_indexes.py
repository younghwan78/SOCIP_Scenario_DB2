"""evidence + write_batches lookup indexes

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-11
"""
from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # evidence is queried by (scenario_ref, variant_ref) from graph loading,
    # simulation result listing, and the query engine; it is also the
    # fastest-growing table (simulation accumulation).
    op.create_index("idx_ev_scenario_variant", "evidence", ["scenario_ref", "variant_ref"])
    # explorer _latest_import_batches orders by updated_at desc.
    op.create_index("idx_write_batches_updated_at", "write_batches", ["updated_at"])


def downgrade() -> None:
    op.drop_index("idx_write_batches_updated_at", table_name="write_batches")
    op.drop_index("idx_ev_scenario_variant", table_name="evidence")
