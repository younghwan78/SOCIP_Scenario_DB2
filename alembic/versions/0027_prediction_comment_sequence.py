"""prediction_comments.sequence backfill for DBs created from the pre-18853f6 revision 0024

0024 was edited in place (18853f6: revision id renamed, sequence identity column added,
comment-order index switched to (prediction_ref, sequence)); DBs already past 0024 never got
them. Idempotent: no-op on DBs created from the current 0024. Existing comments are numbered
in their previous display order (created_at, id) before the identity takes over.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE next_seq bigint;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'prediction_comments' AND column_name = 'sequence'
            ) THEN
                ALTER TABLE prediction_comments ADD COLUMN sequence bigint;
                UPDATE prediction_comments c SET sequence = o.rn
                FROM (SELECT id, row_number() OVER (ORDER BY created_at, id) AS rn
                      FROM prediction_comments) o
                WHERE c.id = o.id;
                ALTER TABLE prediction_comments ALTER COLUMN sequence SET NOT NULL;
                SELECT COALESCE(MAX(sequence), 0) + 1 INTO next_seq FROM prediction_comments;
                EXECUTE format(
                    'ALTER TABLE prediction_comments ALTER COLUMN sequence '
                    'ADD GENERATED ALWAYS AS IDENTITY (START WITH %s)', next_seq);
            END IF;
        END $$;
        """
    )
    op.execute("DROP INDEX IF EXISTS idx_prediction_comment_order")
    op.execute("CREATE INDEX idx_prediction_comment_order ON prediction_comments (prediction_ref, sequence)")


def downgrade() -> None:
    # sequence belongs to 0024's current definition; nothing to undo
    pass
