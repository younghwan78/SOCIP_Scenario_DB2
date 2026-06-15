"""align evidence schema column types

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    topology_type = _column_udt("topology_order")
    if topology_type == "jsonb":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION _scenariodb_jsonb_text_array(value jsonb)
            RETURNS text[]
            LANGUAGE sql
            IMMUTABLE
            AS $$
                SELECT CASE
                    WHEN value IS NULL THEN NULL
                    WHEN jsonb_typeof(value) = 'array' THEN ARRAY(SELECT jsonb_array_elements_text(value))
                    ELSE NULL
                END
            $$;
            """
        )
        op.alter_column(
            "evidence",
            "topology_order",
            existing_type=postgresql.JSONB(astext_type=sa.Text()),
            type_=postgresql.ARRAY(sa.Text()),
            postgresql_using="_scenariodb_jsonb_text_array(topology_order)",
        )
        op.execute("DROP FUNCTION _scenariodb_jsonb_text_array(jsonb)")

    calculation_trace_type = _column_udt("calculation_trace")
    if calculation_trace_type == "text":
        op.alter_column(
            "evidence",
            "calculation_trace",
            existing_type=sa.Text(),
            type_=postgresql.JSONB(astext_type=sa.Text()),
            postgresql_using="NULLIF(btrim(calculation_trace), '')::jsonb",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    if _column_udt("topology_order") == "_text":
        op.alter_column(
            "evidence",
            "topology_order",
            existing_type=postgresql.ARRAY(sa.Text()),
            type_=postgresql.JSONB(astext_type=sa.Text()),
            postgresql_using="to_jsonb(topology_order)",
        )


def _column_udt(column_name: str) -> str | None:
    bind = op.get_bind()
    return bind.execute(
        sa.text(
            """
            SELECT udt_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'evidence'
              AND column_name = :column_name
            """
        ),
        {"column_name": column_name},
    ).scalar()
