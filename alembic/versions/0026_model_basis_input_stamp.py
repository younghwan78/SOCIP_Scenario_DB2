"""model_bases.input_stamp backfill for DBs created from the pre-632e974 revision 0025

0025 was edited in place (632e974) to add input_stamp; DBs already stamped at 0025 never got
the column. Idempotent: no-op on DBs created from the current 0025.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE model_bases "
        "ADD COLUMN IF NOT EXISTS input_stamp JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE model_bases "
        "ADD COLUMN IF NOT EXISTS trial JSONB NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade() -> None:
    # columns belong to 0025's current definition; nothing to undo
    pass
