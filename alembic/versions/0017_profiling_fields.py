"""Measured HW/runtime and event latency; lossless sweep persistence."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("soc_platforms", sa.Column("platform_model", JSONB))
    op.add_column("scenarios", sa.Column("provenance", JSONB))
    op.add_column("evidence", sa.Column("hw_task_timing", JSONB))
    op.add_column("evidence", sa.Column("sw_event_latency", JSONB))
    op.add_column("scenarios", sa.Column("parametric_sweeps", JSONB))


def downgrade() -> None:
    op.drop_column("scenarios", "provenance")
    op.drop_column("soc_platforms", "platform_model")
    op.drop_column("scenarios", "parametric_sweeps")
    op.drop_column("evidence", "sw_event_latency")
    op.drop_column("evidence", "hw_task_timing")
