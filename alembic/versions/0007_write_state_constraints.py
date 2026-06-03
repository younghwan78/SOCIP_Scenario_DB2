"""Add write and evidence domain constraints."""

from __future__ import annotations

from alembic import op


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_write_batches_kind",
        "write_batches",
        "kind in ('scenario.variant_overlay', 'scenario.pipeline_patch', 'scenario.import_bundle')",
    )
    op.create_check_constraint(
        "ck_write_batches_status",
        "write_batches",
        "status in ('staged', 'validated', 'validation_failed', 'diff_ready', 'applied')",
    )
    op.create_check_constraint(
        "ck_write_events_action",
        "write_events",
        "action in ('stage', 'validate', 'diff', 'apply')",
    )
    op.create_check_constraint(
        "ck_evidence_kind",
        "evidence",
        "kind in ('evidence.simulation', 'evidence.measurement')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_evidence_kind", "evidence", type_="check")
    op.drop_constraint("ck_write_events_action", "write_events", type_="check")
    op.drop_constraint("ck_write_batches_status", "write_batches", type_="check")
    op.drop_constraint("ck_write_batches_kind", "write_batches", type_="check")
